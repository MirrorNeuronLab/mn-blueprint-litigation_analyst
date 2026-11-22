const assert = require("node:assert/strict");
const test = require("node:test");
const vm = require("node:vm");
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const assets = join(__dirname,"../payloads/domain/workspace_assets");

function snapshot() {
  const make = (id,text,hash) => ({source_id:id,relative_path:id+".txt",text,content_sha256:hash});
  const sent=make("sent","📎 Send notice and request acknowledgment.","a");
  const copy={...sent,source_id:"copy",relative_path:"copy.txt"};
  const denied=make("testimony","I did not receive the notice.","b");
  const undated=make("undated","The records mention an acknowledgment.","c");
  const mixed=make("mixed","Uncertain receipt of notice.","d");
  const sources=[sent,copy,denied,undated,mixed];
  const dates=[
    ...["sent","copy"].map(id=>({unit_id:id,meaning:"Record date",earliest:"2024-04-01",latest:"2024-04-01"})),
    {unit_id:"testimony",meaning:"Testimony given",earliest:"2024-07-12",latest:"2024-07-12"},
    {unit_id:"mixed",meaning:"Record date",earliest:"2024-05-01",latest:"2024-05-31"},
    {unit_id:"sent",meaning:"Termination",earliest:"2024-05-10",latest:"2024-05-10"}
  ];
  const W={casework:{facts:[],aliases:[],elements:[],events:[]},temporal:{events:[]},
    case_query_index:{units:sources.map(s=>[s.source_id,s.source_id,0,Array.from(s.text).length]),dates,links:[]}};
  const ctx=vm.createContext({W,sources,sourceById:new Map(sources.map(s=>[s.source_id,s])),evidenceById:new Map()});
  for(const name of ["casework_model.js","casework_query.js"])vm.runInContext(readFileSync(join(assets,name),"utf8"),ctx);
  return ctx;
}
test("Receipt questions preserve denials, duplicate grouping and unresolved record dates",()=>{
  const ctx=snapshot();
  const result=ctx.cwRunChain(["Which records address receipt?"]);
  assert.equal(result.matches.length,4);
  assert.equal(result.matches.find(row=>row.sid==="sent").copies.size,2);
  assert(result.matches.some(row=>row.quote.includes("did not receive")));
  const refined=ctx.cwRunChain(["Which records address receipt?","Which of those predate termination?"]);
  assert.deepEqual(Array.from(refined.matches,r=>r.sid),["sent"]);
  assert.deepEqual(Array.from(refined.unknown).sort(),["mixed","undated"]);
  assert.equal(refined.plan.bounds[0].day,"2024-05-10");
  ctx.W.case_query_index.dates.push({unit_id:"testimony",meaning:"Termination",earliest:"2024-07-12",latest:"2024-07-12"});
  assert.match(ctx.cwRunChain(["Which records address receipt before termination?"]).error,/Several dates/);
  assert.match(ctx.cwRunChain(["Which of those predate termination?"]).error,/before narrowing/);
});
test("Unicode offsets survive Word quotes, and similar names stay separate",()=>{
  const ctx=snapshot(), s=ctx.sources[0];
  assert.equal(ctx.cwSlice(s,2,6),"Send");
  assert.equal(ctx.cwSlice(s,0,1),"📎");
  assert.equal(ctx.cwCurrent({source:"sent",hash:"a",start:2,end:6,quote:"Send"}),true);
  assert.equal(ctx.cwMentions("J. Lee signed.","J. Lee"),true);
  assert.equal(ctx.cwMentions("J. Leeman signed.","J. Lee"),false);
  assert.equal(ctx.cwMentions("Lee met Jordan.","L.e"),false);
});
test("Counsel working data is omitted from an approved excerpt briefing",()=>{
  const code=readFileSync(join(assets,"workspace.js"),"utf8");
  const W={findings:[],evidence:[],sources:[],graph:{edges:[],nodes:[]},temporal:{},analysis:{},capabilities:{},
    casework:{facts:[{wording:"PRIVATE_CASEWORK"}]},case_query_index:{units:["PRIVATE_CASEWORK"]},
    casework_changed_sources:["PRIVATE_CASEWORK"],casework_import_note:"PRIVATE_CASEWORK"};
  const ctx=vm.createContext({W,document:{getElementById:()=>({value:"Authorized reviewer",close(){}})},
    visibleFindings:()=>[],currentReview:f=>f,sourceById:new Map(),state:{},defaults:{},savedViews:[],decisions:[],
    download:(_name,data)=>{ctx.exported=data;},pageFor:data=>data,notice(){}});
  vm.runInContext(code.slice(code.indexOf("function briefing() {"),code.indexOf('\ndocument.addEventListener("click"')),ctx);
  ctx.briefing();
  assert.equal(ctx.exported.package_mode,"approved_excerpt_briefing");
  assert(!JSON.stringify(ctx.exported).includes("PRIVATE_CASEWORK"));
});

