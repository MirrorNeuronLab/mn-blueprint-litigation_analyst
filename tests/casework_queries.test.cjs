const assert = require("node:assert/strict");
const test = require("node:test");
const vm = require("node:vm");
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const assets = join(__dirname,"../payloads/domain/workspace_assets");

function snapshot() {
  const make = (id,text,hash) => ({source_id:id,relative_path:id+".txt",text,content_sha256:hash});
  const sent=make("sent","📎 Send notice and request acknowledgment.","a");
  const first=make("shipment-a","Morgan acknowledged shipment A.","b");
  const other=make("shipment-b","Morgan acknowledged shipment B.","c");
  const unrelated=make("packing","The packing slip lists three items.","d");
  const sources=[sent,first,other,unrelated];
  const W={casework:{facts:[],aliases:[],elements:[{id:"receipt",title:"Receipt of shipment A"}],events:[]},
    casework_changed_sources:["shipment-a","shipment-b","packing"],temporal:{events:[]},
    case_query_index:{units:sources.map(s=>[s.source_id,s.source_id,0,Array.from(s.text).length]),dates:[]}};
  const ctx=vm.createContext({W,sources,sourceById:new Map(sources.map(s=>[s.source_id,s])),evidenceById:new Map()});
  for(const name of ["casework_model.js","casework_changes.js"])vm.runInContext(readFileSync(join(assets,name),"utf8"),ctx);
  return ctx;
}
test("Production changes still find related wording for the same proof element and shipment",()=>{
  const changes=snapshot().cwImpacts().byElement.get("receipt");
  assert.deepEqual(Array.from(changes,row=>row.id),["shipment-a"]);
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
    casework_changed_sources:["PRIVATE_CASEWORK"],casework_import_note:"PRIVATE_CASEWORK",
    case_brief:{titles:{private:"PRIVATE_CASEWORK"},highlights:[{excerpt:"PRIVATE_CASEWORK"}]}};
  const ctx=vm.createContext({W,document:{getElementById:()=>({value:"Authorized reviewer",close(){}})},
    visibleFindings:()=>[],currentReview:f=>f,sourceById:new Map(),state:{},defaults:{},savedViews:[],decisions:[],
    download:(_name,data)=>{ctx.exported=data;},pageFor:data=>data,notice(){}});
  vm.runInContext(code.slice(code.indexOf("function briefing() {"),code.indexOf('\ndocument.addEventListener("click"')),ctx);
  ctx.briefing();
  assert.equal(ctx.exported.package_mode,"approved_excerpt_briefing");
  assert(!JSON.stringify(ctx.exported).includes("PRIVATE_CASEWORK"));
});

