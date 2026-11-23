/* Start with the first synthetic report. Publish its supplement from the actual browser review. */
const {chromium, expect} = require("@playwright/test");
const {pathToFileURL} = require("node:url");
const {join} = require("node:path");
const {readFile} = require("node:fs/promises");
const {execFileSync} = require("node:child_process");
const assert = require("node:assert/strict");
const JSZip = require("../payloads/domain/workspace_assets/vendor/jszip.min.js");

async function pilot(root) {
  const browser = await chromium.launch();
  const page = await browser.newPage({viewport:{width:1280,height:850}});
  page.setDefaultTimeout(8000);
  const errors=[], network=[];
  page.on("pageerror",e=>errors.push(e.message));
  page.on("request",r=>{if(/^https?:/.test(r.url()))network.push(r.url());});
  const button=(name)=>page.getByRole("button",{name,exact:true});
  const nav=async(route)=>{
    const tab=page.getByRole("tab",{name:route,exact:true});
    if(!await tab.isVisible())await page.getByRole("button",{name:"More views"}).click();
    await tab.click();
  };
  const form=()=>page.locator("#cw-editor");
  async function expectReadableFields(fields) {
    const sizes = await fields.evaluateAll(elements => elements.map(field => {
      const style = getComputedStyle(field);
      const available = field.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
      const {left, right} = field.getBoundingClientRect();
      return { name: field.name, available, lineHeight: parseFloat(style.lineHeight), left, right, viewport: document.documentElement.clientWidth };
    }));
    assert(sizes.length > 0, "Expected a visible form field");
    for (const {name, available, lineHeight, left, right, viewport} of sizes) {
      assert(available + 1 >= lineHeight, `${name} has ${available}px for a ${lineHeight}px text line`);
      assert(left >= -1 && right <= viewport + 1, `${name} extends past the edge of the screen`);
    }
  }
  async function download(name,trigger){
    const promise=page.waitForEvent("download");
    await trigger();
    const result=await promise;await result.saveAs(join(root,name));
  }
  async function capture(filename,quote,wording,role,pin){
    await nav("Evidence");
    await page.locator("tr").filter({hasText:filename}).getByRole("button",{name:"View source",exact:true}).click();
    const viewer=page.locator("#source-dialog .source-text");await expect(viewer).toBeVisible();
    await viewer.evaluate((el,phrase)=>{
      const node=el.firstChild,where=node.textContent.indexOf(phrase);
      if(where<0)throw Error("Missing pilot quotation");
      const range=document.createRange();range.setStart(node,where);range.setEnd(node,where+phrase.length);
      const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);
    },quote);
    await button("Capture fact").click();
    await form().getByLabel("Factual proposition").fill(wording);
    await form().getByLabel("Proof element").selectOption({label:"Notice before termination · Customer received notice for shipment A"});
    await form().getByLabel("Evidence role").selectOption(role);
    await form().getByLabel("Speaker or witness",{exact:false}).fill("Jordan Lee");
    await form().getByLabel("Your name").fill("Pilot counsel");
    await form().getByLabel("Bates or transcript",{exact:false}).fill(pin);
    await form().getByLabel("I checked this pinpoint",{exact:false}).check();
    await form().getByLabel("I reviewed this wording",{exact:false}).check();
    await button("Save fact").click();
    await expect(form()).not.toBeVisible();
    await page.keyboard.press("Escape");
  }
  try{
    const reportUrl=pathToFileURL(join(root,"first/web/index.html")).href;
    await page.goto(reportUrl);
    await expect(page.getByRole("tab")).toHaveCount(10);
    await expect(button("More views")).toHaveCount(0);
    await expect(button("Explore case graph")).toBeVisible();
    await expect(page.locator("#case-graph-canvas")).toHaveCount(0);
    await expect(button("Ask the case graph")).toHaveCount(0);
    await button("Explore case graph").click();
    await expect(page.getByLabel("Find in graph")).toBeVisible();
    await expect(button("Ask the graph")).toHaveCount(0);
    const stage=page.getByRole("region",{name:"Interactive case graph"});
    const initialZoom=await page.locator("#case-graph-scale").textContent();
    await button("Zoom in").click();
    await expect(page.locator("#case-graph-scale")).not.toHaveText(initialZoom);
    await stage.focus();await page.keyboard.press("Home");
    await button("Inspect Proof element · Customer received notice for shipment A").click();
    await button("Trace to case goal").click();
    await expect(button("Trace to case goal")).toHaveAttribute("aria-pressed","true");
    await expect(stage.locator(".case-graph-node.is-dim")).not.toHaveCount(0);
    await nav("People & events");await button("Witness preparation").click();
    const witnessForm = page.locator("#cw-witness-filter");
    await expect(witnessForm.getByLabel("Witness", {exact:true})).toBeDisabled();
    await expect(witnessForm.locator('[name="witness"] option:checked')).toHaveText("No witnesses recorded");
    await expect(button("Choose witness and issue")).toBeDisabled();
    await expectReadableFields(witnessForm.locator("select"));
    await page.goto(reportUrl+"#"+encodeURIComponent(JSON.stringify({view:"Case questions"})));
    await expect(page.getByRole("heading",{name:"Questions",exact:true})).toBeVisible();
    await expect(button("Issue review")).toHaveAttribute("aria-pressed","true");
    await expect(button("Ask the graph")).toHaveCount(0);
    await expect(page.getByLabel("Question about this matter")).toHaveCount(0);
    await button("Proof chart").click();
    await expect(page.locator("#content")).toContainText("Open proof gap");
    await button("Add element").click();
    await expectReadableFields(form().locator('select, input[type="text"]'));
    await form().getByLabel("Type",{exact:true}).selectOption("Claim");
    await form().getByLabel("Claim, defense or issue").fill("Delivery obligation");
    await form().getByLabel("Fact to establish").fill("Identity of signer");
    await button("Add element").last().click();
    await expect(page.getByRole("heading",{name:"Identity of signer"})).toBeVisible();
    await capture("deposition.txt","I did not receive the notice for shipment A before termination.","Witness denies receipt of A","Contrary","Tr. 12:4–7");
    await capture("shipment-b.txt","Jordan Lee signed for shipment B and acknowledged receipt of its notice.","Receipt relates to shipment B","Context","ACME000042");
    await capture("deposition.txt","Jordan Lee also used the name J. Lee for shipment B.","Jordan Lee used J. Lee","Context","Tr. 12:4–7");
    await nav("Questions");await button("Proof chart").click();
    const el=page.locator("article.card").filter({has:page.getByRole("heading",{name:"Customer received notice for shipment A"})});
    await expect(el).toContainText("Open proof gap");
    await el.getByRole("button",{name:"Track discovery gap"}).click();
    await form().getByLabel("Record sought").fill("Signed acknowledgment for shipment A");
    await form().getByLabel("What would resolve the question?").fill("Signed receipt for the same shipment");
    await form().getByLabel("Owner",{exact:true}).fill("Pilot paralegal");
    await form().getByLabel("Internal target").fill("2024-05-09");
    await button("Save task").click();
    await button("Discovery").click();
    await expect(page.locator("#content")).toContainText("Overdue");
    await button("Proof chart").click();
    await el.getByRole("button",{name:"Prepare witness"}).click();
    await expect(witnessForm.getByLabel("Witness", {exact:true})).toHaveValue("Jordan Lee");
    await expect(button("Choose witness and issue")).toBeEnabled();
    await page.setViewportSize({width:390,height:850});
    await expect(button("More views")).toBeVisible();
    await expect(page.getByRole("tab",{name:"People & events"})).toHaveAttribute("aria-selected","true");
    await page.evaluate(() => { document.documentElement.style.fontSize = "200%"; });
    await expectReadableFields(witnessForm.locator("select"));
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.evaluate(() => document.documentElement.style.removeProperty("font-size"));
    await page.setViewportSize({width:1280,height:850});
    await button("Choose witness and issue").click();
    await button("Add comparison question").click();
    await form().getByLabel("Witness’s own statement").selectOption({label:"Witness denies receipt of A"});
    await form().getByLabel("Comparison exhibit").selectOption({label:"Receipt relates to shipment B"});
    await form().getByLabel("Counsel’s explanation",{exact:false}).fill("These records describe different shipments.");
    await button("Save question").click();
    await expect(page.locator("#content")).toContainText("different shipments");
    await download("deposition-outline.docx",()=>button("Download editable outline").click());
    await button("Identities").click();await button("Review an alias").click();
    await form().getByLabel("Person",{exact:true}).fill("Jordan Lee");
    await form().getByLabel("Name, title or address",{exact:false}).fill("J. Lee");
    await form().getByLabel("Passage establishing this link").selectOption({label:"Jordan Lee used J. Lee"});
    await form().getByLabel("Reviewed by").fill("Pilot counsel");
    await button("Confirm link").click();
    await nav("Case graph");
    await page.getByRole("searchbox",{name:"Find in graph"}).fill("J. Lee");
    await button("Search graph").click();
    await button("Inspect Confirmed alias · J. Lee").click();
    const graphDetail=page.locator("#case-graph-detail");
    await graphDetail.getByText("Connections (1)",{exact:true}).click();
    await graphDetail.getByRole("button",{name:"Confirmed identity · Jordan Lee"}).click();
    await expect(graphDetail.getByRole("heading",{name:"Confirmed identity",exact:true})).toBeVisible();
    await graphDetail.locator('[data-action="evidence"]').click();
    await expect(page.locator("#cited-span")).toHaveText("Jordan Lee also used the name J. Lee for shipment B.");
    await page.keyboard.press("Escape");
    await nav("People & events");await button("Identities").click();await button("Reverse link").click();
    await form().getByLabel("Reviewed by").fill("Pilot counsel");await button("Reverse link").last().click();
    await expect(page.locator("#content")).toContainText("Reversal");
    await nav("Timeline");await expect(page.locator("#content")).toContainText("early April 2024");
    await nav("Reports");await button("Reviewed briefing").click();
    await download("statement-of-facts.docx",()=>button("Download statement of facts (.docx)").click());
    await download("counsel-review-sheet.docx",()=>button("Download counsel review sheet (.docx)").click());
    await download("saved-owner.html",()=>button("Save copy").click());
    await page.goto(pathToFileURL(join(root,"saved-owner.html")).href);
    await nav("Questions");await button("Proof chart").click();
    await expect(page.locator("#content")).toContainText("ACME000042");
    await page.locator("#content .cw-row").filter({hasText:"Witness denies receipt of A"}).getByRole("button",{name:"Open passage"}).click();
    await expect(page.locator("#cited-span")).toHaveText("I did not receive the notice for shipment A before termination.");
    await page.keyboard.press("Escape");
    await page.getByRole("button",{name:"Actions",exact:true}).click();
    await download("review-from-browser.json",()=>page.getByText("Export review decisions",{exact:true}).click());
    const packet=JSON.parse(await readFile(join(root,"review-from-browser.json"),"utf8"));
    assert.equal(packet.casework.tasks.length,1);assert.equal(packet.casework.queries.length,0);
    const second=join(root,"supplement-"+Date.now());
    execFileSync(process.env.PILOT_PYTHON||"python3",[join(__dirname,"test_casework.py"),second,"--review",join(root,"review-from-browser.json")]);
    await page.goto(pathToFileURL(join(second,"web/index.html")).href);
    await nav("Review history");await button("Changes").click();
    await expect(page.locator("#content")).toContainText("acknowledge receipt");
    await expect(page.locator("#content")).toContainText("Deposition question");
    await expect(page.locator("#content")).toContainText("Statement paragraph");
    const addition=page.locator(".cw-split").filter({hasText:"I, Jordan Lee, acknowledge receipt of the notice for shipment A"}).first();
    await addition.getByRole("button",{name:"Open passage"}).click();
    await expect(page.locator("#cited-span")).toContainText("acknowledge receipt");
    await page.keyboard.press("Escape");
    await nav("Reports");await button("Reviewed briefing").click();
    await expect(button("Download statement of facts (.docx)")).toBeDisabled();
    await nav("Questions");
    await expect(button("Issue review")).toHaveAttribute("aria-pressed","true");
    await page.setViewportSize({width:510,height:850});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.setViewportSize({width:1280,height:850});
    await page.screenshot({path:join(root,"case-questions.png")});
    await nav("Case graph");
    await expect(page.getByLabel("Find in graph")).toBeVisible();
    await page.getByRole("button",{name:/^Inspect /}).first().click();
    await page.screenshot({path:join(root,"case-graph.png")});
    await capture("acknowledgment.txt","I, Jordan Lee, acknowledge receipt of the notice for shipment A on April 25, 2024.","Jordan Lee acknowledged notice for shipment A on April 25","Support","ACME000057");
    await nav("Questions");await button("Discovery").click();await button("Record resolution").click();
    await form().getByLabel("Evidence that meets the closure test").selectOption({label:"Jordan Lee acknowledged notice for shipment A on April 25"});
    await form().getByLabel("How this passage resolves the request").fill("The signed record identifies shipment A and predates termination.");
    await form().getByLabel("Reviewed by").fill("Second reviewer");await button("Close task").click();
    await expect(page.locator("#content")).toContainText("Closed");
    await page.locator("#content .cw-row").filter({hasText:"Signed acknowledgment for shipment A"}).getByRole("button",{name:"Open passage"}).click();
    await expect(page.locator("#cited-span")).toContainText("Jordan Lee, acknowledge receipt");
    await page.keyboard.press("Escape");
    await nav("Reports");await button("Reviewed briefing").click();
    await download("supplemental-statement.docx",()=>button("Download statement of facts (.docx)").click());
    await nav("Questions");await button("Proof chart").click();
    await download("completed-review.html",()=>button("Save copy").click());
    await page.goto(pathToFileURL(join(root,"first/case/privilege_log.html")).href);
    await expectReadableFields(page.locator('#log-entry input:not([type="checkbox"])'));
    await button("PRIV-001").click();await page.getByRole("textbox",{name:"Reviewed by"}).fill("Pilot counsel");
    await page.getByLabel("Counsel approved this metadata",{exact:false}).check();await button("Save entry").click();
    await page.locator('[data-field="participants"]').uncheck();
    await download("privilege-log.csv",()=>button("Download previewed CSV").click());
    const csv=await readFile(join(root,"privilege-log.csv"),"utf8");
    assert(csv.includes("PRIV-001"));assert(!csv.includes("Participants"));assert(!csv.includes("shipment"));
    await download("private-working-copy.html",()=>button("Save counsel working copy").click());
    await page.goto(pathToFileURL(join(root,"private-working-copy.html")).href);
    await expect(page.locator('[data-field="participants"]')).not.toBeChecked();
    await button("PRIV-001").click();
    await page.getByRole("textbox",{name:"Description"}).fill("Revised internal description");
    await expect(page.locator('[name="approved"]')).not.toBeChecked();
    for(const [file,expected] of [
      ["statement-of-facts.docx","ACME000042"],["supplemental-statement.docx","ACME000057"],
      ["counsel-review-sheet.docx","I did not receive the notice"],["deposition-outline.docx","different shipments"]
    ]){
      const zip=await JSZip.loadAsync(await readFile(join(root,file)));
      const xml=await zip.file("word/document.xml").async("string");
      assert(xml.includes(expected));assert(xml.includes("w:bookmarkStart"));assert(xml.includes("w:hyperlink"));
      assert(!xml.includes("PRIV-001"));
      if(file.includes("statement")){assert(xml.includes("w:numPr"));assert(!xml.includes("Witness denies receipt of A"));}
    }
    assert.deepEqual(errors,[]);assert.deepEqual(network,[]);
    console.log("Offline pilot passed in Chromium.");
  }catch(err){console.error(await page.locator("body").innerText().catch(()=>""));console.error(errors);throw err;}
  finally{await browser.close();}
}
pilot(process.argv[2]).catch(e=>{console.error(e);process.exitCode=1;});

