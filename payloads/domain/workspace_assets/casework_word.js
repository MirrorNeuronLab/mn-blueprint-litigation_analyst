"use strict";
const cwWordMime="application/vnd.openxmlformats-officedocument.wordprocessingml.document";
function cwWordData(kind,issue){
  const book=cwBook(), changes=cwImpacts(), impacts=changes.material, paragraphs=[], exhibits=new Map();
  const titles={statement:"Statement of facts",review:"Counsel review sheet",outline:"Deposition outline"};
  const add=(text,style="Normal",extra={})=>paragraphs.push({text,style,...extra});
  function cite(a){
    if(!a)return;
    if(!cwCurrent(a)){add("Historical citation · "+cwLocator(a)+" · SHA-256 "+a.hash,"Citation");return;}
    const key=JSON.stringify([a.source,a.hash,a.start,a.end,a.pin]);
    if(!exhibits.has(key))exhibits.set(key,{...a,number:exhibits.size+1});
    const n=exhibits.get(key).number;
    add("Exhibit "+n+" · "+cwLocator(a),"Citation",{link:"exhibit_"+n});
  }
  function comparisonStatus(o){
    if(cwOutlineNeedsReview(o,changes.byElement.get(o.element)))
      return "Recheck both passages and the witness attribution. Earlier disposition: "+(o.resolution||"Discrepancy awaiting review");
    return o.resolution||"Discrepancy awaiting review";
  }
  function citeEvidence(ids){
    for(const id of new Set(ids)){
      const p=evidenceById.get(id);
      if(p)cite({source:p.source_id,hash:p.content_sha256,start:p.start_offset,end:p.end_offset,quote:p.text,pin:""});
    }
  }
  add(titles[kind],"Title");
  add(W.title+" · "+(W.sample?"Synthetic matter · ":"")+"Counsel working draft");
  if(kind==="statement"){
    add("Numbered propositions use the wording reviewed for this matter. Select an exhibit citation to read its exact passage.");
    for(const f of book.facts){
      if(!cwFactReady(f,impacts))continue;
      add(f.wording,"Normal",{numbered:true});cite(f.anchor);
    }
    for(const f of eligibleBriefing()){
      add(f.reviewed_text,"Normal",{numbered:true});citeEvidence([...f.supporting_evidence,...f.counter_evidence]);
      if(f.limitations)add(f.limitations,"Citation");
    }
    if(!paragraphs.some(p=>p.numbered))throw new Error("Review a current, eligible fact before downloading a statement.");
  }else if(kind==="review"){
    add("Use this internal sheet to check adverse passages, disputed wording and changes before using the statement.");
    for(const f of book.facts){
      if(f.role!=="Contrary"&&f.approved&&cwCurrent(f.anchor)&&!cwNeedsReview(f,impacts.get(f.id)))continue;
      add(f.wording,"Heading1");add(f.role+" · "+f.actor+(cwCurrent(f.anchor)?"":" · Earlier source version"));
      add(f.anchor.quote);cite(f.anchor);
    }
    for(const raw of W.findings){
      const f=currentReview(raw);
      if(!f.counter_evidence.length&&["Reviewed with qualification","Revised"].includes(f.review_state))continue;
      add(f.title,"Heading1");add(f.review_state+" · "+(f.reviewed_text||f.assessment));add(f.limitations||"");
      citeEvidence(f.counter_evidence);
    }
    for(const o of book.outlines){
      add(o.witness+" · "+o.question,"Heading1");add(comparisonStatus(o));
      cite(cwFact(o.statement)?.anchor);cite(cwFact(o.exhibit)?.anchor);
    }
  }else{
    const witness=cwWitness||cwWitnesses()[0]||"";
    add(witness+" · "+(cwElement(issue)?.title||""),"Heading1");
    for(const o of book.outlines.filter(x=>x.witness===witness&&x.element===issue)){
      add(o.question,"Normal",{numbered:true});
      for(const [label,id] of [["Witness statement",o.statement],["Comparison exhibit",o.exhibit]]){
        const f=cwFact(id);add(label+" · "+f.wording);add(f.anchor.quote);cite(f.anchor);
        if(!cwCurrent(f.anchor))add("Earlier source version. Recheck this passage.","Citation");
      }
      add(comparisonStatus(o),"Citation");
    }
  }
  if(exhibits.size){
    add("Exhibit index","Heading1");
    for(const a of exhibits.values()){
      add("Exhibit "+a.number+" · "+cwLocator(a),"Heading2",{bookmark:a.number});
      add(a.quote);add("Normalized source SHA-256 "+a.hash,"Citation");
    }
  }
  return paragraphs;
}
function cwXml(value){
  return String(value||"").replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]/gu,"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&apos;"}[c]));
}
function cwWordParagraph(p){
  const run='<w:r>'+String(p.text).split(/\r?\n/).map((line,i)=>(i?"<w:br/>":"")+'<w:t xml:space="preserve">'+cwXml(line)+'</w:t>').join("")+'</w:r>';
  const properties='<w:pPr><w:pStyle w:val="'+p.style+'"/>'+(p.numbered?'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>':'')+'</w:pPr>';
  return '<w:p>'+properties+(p.bookmark?'<w:bookmarkStart w:id="'+p.bookmark+'" w:name="exhibit_'+p.bookmark+'"/>':'')+
    (p.link?'<w:hyperlink w:anchor="'+p.link+'">'+run+'</w:hyperlink>':run)+(p.bookmark?'<w:bookmarkEnd w:id="'+p.bookmark+'"/>':'')+'</w:p>';
}
async function cwCreateWord(paragraphs){
  const zip=new JSZip(), w='http://schemas.openxmlformats.org/wordprocessingml/2006/main';
  const pkg='http://schemas.openxmlformats.org/package/2006/relationships',rel='http://schemas.openxmlformats.org/officeDocument/2006/relationships/';
  const xml='<?xml version="1.0" encoding="UTF-8" standalone="yes"?>';
  zip.file('[Content_Types].xml',xml+'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'+
    ['document','styles','numbering'].map(n=>'<Override PartName="/word/'+n+'.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.'+(n==='document'?'document.main':n)+'+xml"/>').join('')+'</Types>');
  zip.file('_rels/.rels',xml+'<Relationships xmlns="'+pkg+'"><Relationship Id="rId1" Type="'+rel+'officeDocument" Target="word/document.xml"/></Relationships>');
  zip.file('word/_rels/document.xml.rels',xml+'<Relationships xmlns="'+pkg+'">'+['styles','numbering'].map((n,i)=>'<Relationship Id="rId'+(i+1)+'" Type="'+rel+n+'" Target="'+n+'.xml"/>').join('')+'</Relationships>');
  const style=(name,size,bold)=>'<w:style w:type="paragraph" w:styleId="'+name+'"><w:name w:val="'+name+'"/><w:pPr>'+(bold?'<w:keepNext/>':'')+'<w:spacing w:before="'+(bold?140:0)+'" w:after="100"/></w:pPr><w:rPr>'+(bold?'<w:b/>':'')+'<w:sz w:val="'+size+'"/></w:rPr></w:style>';
  zip.file('word/styles.xml',xml+'<w:styles xmlns:w="'+w+'"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Cambria" w:hAnsi="Cambria"/><w:sz w:val="22"/></w:rPr></w:rPrDefault></w:docDefaults>'+
    style('Normal',22,false)+style('Title',38,true)+style('Heading1',28,true)+style('Heading2',24,true)+style('Citation',19,false)+'</w:styles>');
  zip.file('word/numbering.xml',xml+'<w:numbering xmlns:w="'+w+'"><w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="singleLevel"/><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/><w:pPr><w:ind w:left="480" w:hanging="340"/></w:pPr></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>');
  zip.file('word/document.xml',xml+'<w:document xmlns:w="'+w+'"><w:body>'+paragraphs.map(cwWordParagraph).join('')+'<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1080" w:bottom="1080" w:left="1320" w:right="1320"/></w:sectPr></w:body></w:document>');
  return zip.generateAsync({type:"uint8array",compression:"DEFLATE"});
}
async function cwDownloadWord(kind,id){
  if(state.supportingOnly)throw new Error("Restore counterevidence before exporting review work.");
  const names={statement:"statement-of-facts",review:"counsel-review-sheet",outline:"deposition-outline"};
  download(names[kind]+".docx",await cwCreateWord(cwWordData(kind,id)),cwWordMime);
}
