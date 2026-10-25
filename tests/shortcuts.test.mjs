import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {transform} from 'esbuild';
const {code}=await transform(await readFile(new URL('../src/host/operations.ts',import.meta.url),'utf8'),{loader:'ts',format:'esm'});
const {Operations,bindingFromEvent,bindingError,shortcutAction,shortcutFor,shortcutHint}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const event=(code,mods={})=>({code,ctrlKey:false,altKey:false,shiftKey:false,metaKey:false,...mods});
test('custom bindings replace defaults; clearing disables the old combination',()=>{
 const defaults=event('KeyF',{altKey:true,shiftKey:true}),custom=event('KeyG',{ctrlKey:true,altKey:true});
 assert.equal(shortcutAction(defaults),'toggle.focus');
 assert.equal(shortcutAction(defaults,{'toggle.focus':'Ctrl+Alt+KeyG'}),undefined);
 assert.equal(shortcutAction(custom,{'toggle.focus':'Ctrl+Alt+KeyG'}),'toggle.focus');
 assert.equal(shortcutAction(defaults,{'toggle.focus':''}),undefined);
 assert.equal(shortcutFor('open.character'),'');
 assert.equal(shortcutFor('toggle.focus',{'toggle.focus':'invalid'}),'Alt+Shift+KeyF');
});
test('ordinary typing, send, editing and browser navigation cannot become shortcuts',()=>{
 for(const binding of ['KeyA','Shift+KeyA','Enter','Ctrl+KeyC','Ctrl+KeyL','Meta+KeyW','Alt+ArrowLeft','Ctrl+Digit2','Alt+F4','Ctrl+Tab','Ctrl+F5'])assert(bindingError(binding),binding);
 for(const binding of ['','Alt+Shift+Digit1','Ctrl+Alt+KeyG','Meta+Shift+KeyE','Ctrl+Shift+F8'])assert.equal(bindingError(binding),null,binding);
 assert.equal(shortcutAction(event('Enter')),undefined);
 assert.equal(shortcutAction(event('KeyA')),undefined);
 assert(bindingError('Alt+Alt+KeyG'));
});
test('physical keys and modifier-only events are handled consistently',()=>{
 assert.equal(bindingFromEvent(event('KeyG',{ctrlKey:true,altKey:true,shiftKey:true})),'Ctrl+Alt+Shift+KeyG');
 assert.equal(bindingFromEvent(event('ShiftLeft',{shiftKey:true})), '');
 assert.equal(shortcutHint('toggle.focus',{'toggle.focus':'Meta+Shift+KeyE'}),'⌘+Shift+E');
 assert.equal(shortcutHint('toggle.focus',{'toggle.focus':''}),'');
});
test('registered actions share dispatch and can be removed without affecting peers',()=>{
 const ops=new Operations(),seen=[];
 const remove=ops.register('open.world',()=>seen.push('world'));
 ops.register('open.persona',()=>seen.push('persona'));
 ops.run('open.world');remove();ops.run('open.persona');
 assert.deepEqual(seen,['world','persona']);assert.throws(()=>ops.run('open.world'),/操作不可用/);
 ops.clear();assert.throws(()=>ops.run('open.persona'),/操作不可用/);
});
