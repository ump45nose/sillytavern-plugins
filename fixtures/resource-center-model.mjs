import http from 'node:http';
const records=[];
const server=http.createServer(async(req,res)=>{
 if(req.url==='/requests'){res.setHeader('content-type','application/json');return res.end(JSON.stringify(records))}
 if(req.url!=='/v1/chat/completions'){res.writeHead(404).end();return}
 let text='';for await(const chunk of req)text+=chunk;
 const body=JSON.parse(text);records.push({model:body.model,stream:!!body.stream});
 if(body.model==='fixture-rate'){res.writeHead(429,{'content-type':'application/json'}).end(JSON.stringify({error:{type:'rate_limit_error',message:'fixture rate limit'}}));return}
 const usage={prompt_tokens:23,completion_tokens:7};
 if(!body.stream){res.setHeader('content-type','application/json');res.end(JSON.stringify({choices:[{message:{role:'assistant',content:'fixture reply'},finish_reason:'stop'}],usage}));return}
 res.writeHead(200,{'content-type':'text/event-stream'});res.write('data: {"choices":[{"delta":{"content":"fixture reply"}}]}\n\n');
 const timer=setTimeout(()=>res.end('data: '+JSON.stringify({choices:[{delta:{},finish_reason:'stop'}],usage})+'\n\ndata: [DONE]\n\n'),body.model==='fixture-slow'?3000:100);
 res.on('close',()=>clearTimeout(timer));
});server.listen(4010,'0.0.0.0');
