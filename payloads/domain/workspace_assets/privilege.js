"use strict";
const metadata = JSON.parse(document.getElementById("log-data").textContent);
const fields = metadata.fields;
const logRows = metadata.rows;
const labels = {reference:"Document reference",date:"Date",participants:"Participants",document_type:"Document type",description:"Description",basis:"Counsel’s basis",reviewer:"Reviewed by"};
const selected = new Set((metadata.selected_fields||fields).filter(k=>fields.includes(k)));
const escapeLog = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const eligible = row => row.approved === true && ["reference","description","basis","reviewer"].every(k=>row[k]?.trim());
const pending = row => ["reference","description","basis","reviewer"].filter(k=>!row[k]?.trim()).map(k=>labels[k]);
const input = key => '<label>'+labels[key]+'<input name="'+key+'" maxlength="500"></label>';
const statusLog = message => {document.getElementById("log-status").textContent=message;};
let editing = -1;
function showLog(draft) {
  const columns = fields.filter(k=>selected.has(k)), ready = logRows.filter(eligible);
  document.getElementById("log").innerHTML = '<h2>Privilege log</h2><p>Enter only metadata counsel has authorized for this worksheet.</p>'+
    '<form id="log-entry" class="cw-form"><h3>'+ (editing<0?"Add a document":"Review document")+'</h3>'+fields.map(input).join("")+
    '<label><input type="checkbox" name="approved"> Counsel approved this metadata for export</label><button>Save entry</button></form>'+
    '<h3>Review entries</h3>'+logRows.map((row,i)=>'<p><button data-edit="'+i+'">'+escapeLog(row.reference||"Unnamed entry")+'</button> · '+escapeLog(eligible(row)?"Approved":pending(row).length?"Missing "+pending(row).join(", "):"Awaiting approval")+'</p>').join("")+
    '<h3>Export preview</h3><fieldset><legend>Fields to include</legend>'+fields.map(k=>'<label><input type="checkbox" data-field="'+k+'" '+(selected.has(k)?"checked":"")+'>'+labels[k]+'</label>').join("")+'</fieldset>'+
    '<p>'+ready.length+' approved entries · '+(logRows.length-ready.length)+' entries awaiting review</p>'+
    '<div class="table-wrap"><table><thead><tr>'+columns.map(k=>'<th>'+labels[k]+'</th>').join("")+'</tr></thead><tbody>'+
    ready.map(row=>'<tr>'+columns.map(k=>'<td>'+escapeLog(row[k])+'</td>').join("")+'</tr>').join("")+'</tbody></table></div>'+
    '<button id="log-export" '+(columns.length&&ready.length?"":"disabled")+'>Download previewed CSV</button> <button id="log-save">Save counsel working copy</button>';
  const entry=draft || logRows[editing];
  if(entry) for(const key of [...fields,"approved"]){
    const field=document.forms["log-entry"].elements[key];
    if(key==="approved")field.checked=entry[key];else field.value=entry[key]||"";
  }
}
function logDownload(name, data, type) {
  const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([data],{type}));a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
}
document.addEventListener("submit",event=>{
  if(event.target.id!=="log-entry")return;
  event.preventDefault();
  const form=new FormData(event.target), row=Object.fromEntries(fields.map(k=>[k,String(form.get(k)||"").trim()]));
  row.approved=form.has("approved");
  if(editing<0)logRows.push(row);else logRows[editing]=row;
  editing=-1;showLog();statusLog("Entry saved in this page. Save a counsel working copy to retain it.");
});
document.addEventListener("input",event=>{
  if(event.target.form?.id==="log-entry" && fields.includes(event.target.name))
    event.target.form.elements.approved.checked=false;
});
document.addEventListener("change",event=>{
  const k=event.target.dataset.field;if(!fields.includes(k))return;
  const draft=Object.fromEntries(new FormData(document.forms["log-entry"]));
  if(event.target.checked)selected.add(k);else selected.delete(k);
  metadata.selected_fields=fields.filter(key=>selected.has(key));showLog(draft);
});
document.addEventListener("click",event=>{
  const button=event.target.closest("button");if(!button)return;
  if(button.hasAttribute("data-edit")){editing=Number(button.dataset.edit);showLog();document.forms["log-entry"].elements.reference.focus();}
  if(button.id==="log-export"){
    const keys=fields.filter(k=>selected.has(k));
    const cell=value=>{let s=String(value??"");if(/^[\s]*[=+@-]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';};
    logDownload("privilege-log.csv",[keys.map(k=>labels[k]),...logRows.filter(eligible).map(r=>keys.map(k=>r[k]))].map(r=>r.map(cell).join(",")).join("\r\n"),"text/csv;charset=utf-8");
  }
  if(button.id==="log-save"){
    const html=document.documentElement.cloneNode(true);
    html.querySelector("#log-data").textContent=JSON.stringify(metadata).replace(/</g,"\\u003c");
    html.querySelector("#log").replaceChildren(); html.querySelector("#log-status").replaceChildren();
    logDownload("counsel-privilege-log.html","<!doctype html>\n"+html.outerHTML,"text/html");
  }
});
showLog();
