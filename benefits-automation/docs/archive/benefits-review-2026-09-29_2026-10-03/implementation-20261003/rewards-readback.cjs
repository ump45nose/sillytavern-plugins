const p='/home/yuwk/benefits-automation/platforms/rewards';
const common=require(p+'/browser_common.cjs');
(async()=>{
 const ctx=await require(p+'/node_modules/patchright').request.newContext({storageState:'/vol2/1000/Docker/benefits-automation/acceptance-20261003/state/rewards/default/storage-state.json',proxy:{server:'http://192.168.31.201:7890'}});
 try{const d=await common.readFlyout({request:ctx}); console.log(JSON.stringify(d.flyoutResult.exploreOnBingPromotions.map(r=>({title:r.title,complete:r.complete,current:r.pointProgress,max:r.pointProgressMax,eligibility:r.exclusiveLockedFeatureStatus}))));}finally{await ctx.dispose();}
})().catch(()=>console.log('Readback unavailable; transport details suppressed'));
