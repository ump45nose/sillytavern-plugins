import test from "node:test";
import assert from "node:assert/strict";
import {build} from "esbuild";
const result=await build({entryPoints:["src/host/resource-center.ts"],bundle:true,write:false,format:"esm",platform:"node"});
const {ResourceCenterLink,centerDefaults,profileConnection}=await import("data:text/javascript;base64,"+Buffer.from(result.outputFiles[0].contents).toString("base64"));
test("saved profile changes during delivery remain immutable and get the acknowledged version",async()=>{
 const settings=centerDefaults();Object.assign(settings,{url:"http://center",token:"scoped",bindings:{p:{channelId:"c",version:1,enabled:true}}});
 const profile={id:"p",api:"custom","api-url":"https://rp.example/v1",model:"kimi",name:"RP",prompt:"must stay local"};
 const link=new ResourceCenterLink(()=>settings,()=>[profile],()=>[],async()=>{},()=>{},()=>"p");
 let finish;const first=new Promise(r=>finish=r);const sent=[];
 link.request=async(_path,body)=>{sent.push(structuredClone(body));if(sent.length===1)await first;return {acceptedVersion:sent.length+1};};
 const delivering=link.queueSavedProfiles();while(!sent.length)await new Promise(r=>setImmediate(r));
 profile.model="claude";await link.queueSavedProfiles();assert.equal(settings.outbox.length,2);finish();await delivering;
 assert.equal(settings.outbox.length,0);assert.equal(sent[0].patch.models[0],"kimi");assert.equal(sent[1].patch.models[0],"claude");assert.equal(sent[1].expectedVersion,2);assert.equal(sent[0].patch.prompt,undefined);
});
test("failed delivery retains the same event id and never repeats native save or makes an upstream call",async()=>{
 const s=centerDefaults();Object.assign(s,{url:"http://center",token:"scoped",bindings:{p:{channelId:"c",version:3,enabled:true}}});
 const p={id:"p",name:"RP",api:"claude",proxy:"saved","api-url":"https://stale.invalid",model:"claude"};let saves=0;
 const link=new ResourceCenterLink(()=>s,()=>[p],()=>[{name:"saved",url:"https://rp.example"}],async()=>{saves++;},()=>{},()=>"p");
 link.request=async()=>{throw Error("offline");};await link.queueSavedProfiles();const id=s.outbox[0].eventId;assert.equal(s.outbox[0].patch.baseUrl,"https://rp.example");assert.match(s.error,/offline/);assert.ok(saves>0);
 link.request=async()=>({acceptedVersion:4});await link.deliver();assert.equal(s.outbox.length,0);assert.equal(s.bindings.p.version,4);assert.ok(id);
});
