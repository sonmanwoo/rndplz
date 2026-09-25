"use strict";
const $=id=>document.getElementById(id);
const esc=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let token="",catalog=[],history=[],session=null,selectedModel="",files=[],busy=false,uploading=false,controller=null,streamText="",optimistic=null,retryPayload=null,letter=null,toastTimer,autoScroll=true,publicMode=false;
let modelSelectionOrigin="automatic",modelDefault="",modelSelectionEpoch=0,modelCatalogTicket=0;
let profileBusy=false,profileSubmission=null;
let profileUI=null;
let accountNavigationPending=false,accountInvalidated=false;
let prepareBusy=false,prepareTicket=0,prepareProgress=null;
let composerInputRevision=0,composerComposing=false;
function composerClientLocked(){return accountNavigationPending||accountInvalidated||busy||prepareBusy||profileBusy||uploading;}
function composerSendLocked(){return composerClientLocked()||!!session?.pending;}
function setComposerDraft(value){$("message").value=value;composerInputRevision++;}
function consumeComposerDraft(){const text=$("message").value,stagedEdit=briefEditor?.stagedText===text&&composerInputRevision===briefEditor.stagedComposerRevision?briefEditor:null;setComposerDraft("");return {text,revision:composerInputRevision,attachmentIds:[],stagedEdit};}
function restoreComposerDraft(draft){if(draft&&!accountNavigationPending&&!accountInvalidated&&composerInputRevision===draft.revision&&$("message").value===""){setComposerDraft(draft.text);if(draft.stagedEdit&&briefEditor===draft.stagedEdit&&briefEditor.stagedText===draft.text)briefEditor.stagedComposerRevision=composerInputRevision;}}
let ciBusyStarted=null,retryDisplay=null,responseProgress="";
let drawController=null,drawRenderKey="",drawEpoch=0,animateScoutKey="",drawMetadataController=null;
const formatted=text=>esc(text).replace(/\*\*([^*\n]+)\*\*/g,"<strong>$1</strong>").replace(/`([^`\n]+)`/g,"<code>$1</code>").replace(/^[-*] /gm,"• ");
// Completed assistant presentation only; link navigation does not verify a source or claim.
function formattedAnswer(text,status){
 const raw=String(text??"");
 if(status!=="complete")return formatted(raw);
 let marker="RNDPLZANSWERREADABLE";while(raw.includes(marker))marker+="X";
 const fragments=[],hold=html=>marker+(fragments.push(html)-1)+"END";
 // Protection-only token balancing; uncertain HTML is never interpreted as answer Markdown.
 const voidHtmlTags=/^(area|base|br|col|embed|hr|img|input|link|meta|param|source|track|wbr)$/i;
 function htmlTagAt(start){
  const lead=/^<(\/?)([A-Za-z][A-Za-z0-9:-]*)(?=[\s/>])/.exec(raw.slice(start));
  if(!lead)return null;
  let quote="",at=start+lead[0].length;
  for(;at<raw.length;at++){
   const char=raw[at];
   if(quote){if(char===quote)quote="";continue;}
   if(char==='"'||char==="'"){quote=char;continue;}
   if(char==="<")return null;
   if(char===">"){
    const tail=raw.slice(start+lead[0].length,at);
    if(lead[1]&&tail.trim())return null;
    return {name:lead[2].toLowerCase(),closing:!!lead[1],selfClosing:/\/\s*$/.test(tail),end:at+1};
   }
  }
  return null;
 }
 function htmlProtectionEnd(start){
  const first=htmlTagAt(start);if(!first)return raw.length;
  if(first.closing||first.selfClosing||voidHtmlTags.test(first.name))return first.end;
  const stack=[first.name];let at=first.end;
  while(at<raw.length){
   const next=raw.indexOf("<",at);if(next<0)return raw.length;
   if(raw.startsWith("<!--",next)){
    const close=raw.indexOf("-->",next+4);if(close<0)return raw.length;
    at=close+3;continue;
   }
   const tag=htmlTagAt(next);if(!tag)return raw.length;
   if(tag.closing){
    if(tag.name!==stack[stack.length-1])return raw.length;
    stack.pop();if(!stack.length)return tag.end;
   }else if(!tag.selfClosing&&!voidHtmlTags.test(tag.name))stack.push(tag.name);
   at=tag.end;
  }
  return raw.length;
 }
 let protectedText="",cursor=0,match;
 const protection=/\x60+|~{3,}|</g;
 while((match=protection.exec(raw))){
  const start=match.index,token=match[0];let end=start;
  if(token[0]!=="<"){
   const lineStart=raw.lastIndexOf("\n",start-1)+1;
   const fence=token.length>=3&&/^ {0,3}$/.test(raw.slice(lineStart,start));
   if(fence){
    const closing=new RegExp("^ {0,3}"+token[0]+"{"+token.length+",}[ \\t]*\\r?$","gm");
    closing.lastIndex=start+token.length;const found=closing.exec(raw);end=found?found.index+found[0].length:raw.length;
   }else if(token.charCodeAt(0)===96){
    const closing=/\x60+/g;closing.lastIndex=start+token.length;let found;
    while((found=closing.exec(raw))&&found[0].length!==token.length){}
    end=found?found.index+found[0].length:raw.length;
   }else continue;
  }else if(raw.startsWith("<!--",start)){
   const close=raw.indexOf("-->",start+4);end=close<0?raw.length:close+3;
  }else{end=htmlProtectionEnd(start);}
  protectedText+=raw.slice(cursor,start)+hold(formatted(raw.slice(start,end)));
  cursor=end;protection.lastIndex=end;
 }
 protectedText+=raw.slice(cursor);
 function safeAddress(value){
  if(!value||value.includes(marker)||/[\s\u0000-\u001f\u007f<>"\x60\\]/.test(value))return false;
  try{const url=new URL(value);return url.protocol==="https:"&&!!url.hostname&&!url.username&&!url.password;}catch{return false;}
 }
 function anchor(address,label){
  const visible=label&&label!==address?esc(label)+' <span class="answer-source-address">('+esc(address)+")</span>":esc(address);
  return '<a class="answer-source-link" href="'+esc(address)+'" target="_blank" rel="noopener noreferrer">'+visible+"</a>";
 }
 function trimAddress(value){
  let previous;
  do{
   previous=value;value=value.replace(/[.,!?;:。，！？、…]+$/u,"");
   for(const [open,close] of [["(",")"],["[","]"],["{","}"]]){
    while(value.endsWith(close)&&value.split(close).length>value.split(open).length)value=value.slice(0,-1);
   }
  }while(value!==previous);
  return value;
 }
 function inline(value){
  let prepared="",at=0,hit;const scan=/\[|https:\/\//gi;
  while((hit=scan.exec(value))){
   const start=hit.index;
   if(hit[0]==="["){
    const labelEnd=value.indexOf("](",start+1);
    if(labelEnd<0)continue;
    const label=value.slice(start+1,labelEnd);
    if(!label||/[\n\r[\]]/.test(label)||label.includes(marker))continue;
    let depth=1,end=labelEnd+2;
    for(;end<value.length;end++){
     if(value[end]==="\n"||value[end]==="\r")break;
     if(value[end]==="(")depth++;
     else if(value[end]===")"&&!--depth)break;
    }
    if(depth!==0)continue;
    const address=value.slice(labelEnd+2,end);
    scan.lastIndex=end+1;
    if(!safeAddress(address))continue;
    prepared+=value.slice(at,start)+hold(anchor(address,label));at=end+1;
    continue;
   }
   const afterProtected=new RegExp(marker+"(\\d+)END$").test(value.slice(0,start));
   if(start&&!afterProtected&&/[A-Za-z0-9_:/@.\\-]/.test(value[start-1]))continue;
   const found=/^https:\/\/[^\s\u0000-\u001f\u007f<>"'\x60\\*“”‘’|]+/i.exec(value.slice(start));
   if(!found)continue;
   const address=trimAddress(found[0].split(marker)[0]);if(!safeAddress(address))continue;
   prepared+=value.slice(at,start)+hold(anchor(address));at=start+address.length;scan.lastIndex=at;
  }
  return formatted(prepared+value.slice(at));
 }
 function row(line){
  let value=line.trim();if(!value.includes("|")||/\\\|/.test(value))return null;
  if(value.startsWith("|"))value=value.slice(1);
  if(value.endsWith("|"))value=value.slice(0,-1);
  const cells=value.split("|").map(cell=>cell.trim());
  return cells.length>=2?cells:null;
 }
 function table(block){
  if(block.length<3)return null;
  const header=row(block[0]),separator=row(block[1]);
  if(!header||header.some(cell=>!cell)||!separator||separator.length!==header.length||separator.some(cell=>!/^:?-{3,}:?$/.test(cell)))return null;
  const body=block.slice(2).map(row);if(body.some(cells=>!cells||cells.length!==header.length))return null;
  return '<div class="answer-table-wrap" role="region" aria-label="답변 표 · 가로로 스크롤할 수 있습니다" tabindex="0"><table class="answer-table"><thead><tr>'+
   header.map(cell=>'<th scope="col">'+inline(cell)+"</th>").join("")+"</tr></thead><tbody>"+
   body.map(cells=>"<tr>"+cells.map(cell=>"<td>"+inline(cell)+"</td>").join("")+"</tr>").join("")+"</tbody></table></div>";
 }
 const lines=protectedText.split("\n"),output=[];
 for(let i=0;i<lines.length;){
  if(lines[i].includes("|")){
   let end=i+1;while(end<lines.length&&lines[end].includes("|")&&lines[end].trim())end++;
   const block=lines.slice(i,end);output.push(table(block)??inline(block.join("\n")));i=end;
  }else{
   const heading=/^ {0,3}(#{2,3})[ \t]+(\S.*)$/.exec(lines[i]);
   if(heading){
    const level=heading[1].length+1;
    output.push('<h'+level+' class="answer-heading">'+inline(heading[2])+'</h'+level+'>');
   }else output.push(inline(lines[i]));
   i++;
  }
 }
 return output.join("\n").replace(new RegExp(marker+"(\\d+)END","g"),(_,index)=>fragments[Number(index)]);
}
async function api(path,body,signal){
 if(accountNavigationPending||accountInvalidated)throw new Error("계정이 바뀌고 있어요. 새 화면에서 다시 확인해 주세요.");
 const response=await fetch(path,body===undefined?(signal?{signal}:{}):{method:"POST",headers:{"Content-Type":"application/json","X-RnDplz-Token":token},body:JSON.stringify(body),...(signal?{signal}:{})});
 let data,invalidJSON=false;try{data=await response.json();}catch{invalidJSON=true;}
 if(signal?.aborted)throw attachmentAbortError();
 if(accountInvalidated)throw new Error("이전 계정의 응답을 적용하지 않았습니다.");
 if(!response.ok||invalidJSON){
  const failure=new Error(typeof data?.error==="string"?data.error:response.status===413?"요청 크기가 서버 전송 한도를 넘었어요. (HTTP 413)":response.ok?"서버 응답을 확인하지 못했어요.":"요청을 처리하지 못했어요. (HTTP "+response.status+")");
  failure.status=response.status;failure.code=typeof data?.code==="string"?data.code:response.ok?"invalid_json_response":"http_"+response.status;
  failure.requestId=response.headers?.get?.("x-rndplz-request-id")||response.headers?.get?.("x-request-id")||response.headers?.get?.("x-vercel-id")||null;
  failure.retry_available=data?.retry_available;
  if(["scout_source_changed","scout_source_unsupported"].includes(data?.code))failure.session=data.session;
  throw failure;
 }
 return data;
}
function displayError(message){return message==="http_503"?"일시적으로 응답할 수 없습니다. 잠시 후 다시 시도해 주세요.":message;}
function error(message=""){$("composerError").textContent=displayError(message);$("composerError").hidden=!message;}
function toast(message){clearTimeout(toastTimer);$("toast").textContent=message;$("toast").hidden=false;toastTimer=setTimeout(()=>$ ("toast").hidden=true,5500);}
function modal(id,returnFocus=document.activeElement){
 document.querySelectorAll("dialog[open]").forEach(d=>d.close());const dialog=$(id);dialog.returnFocus=returnFocus;
 if(!dialog.focusReturnBound){dialog.addEventListener("close",()=>{if(!document.querySelector("dialog[open]")&&dialog.returnFocus?.isConnected)dialog.returnFocus.focus();});dialog.focusReturnBound=true;}
 dialog.showModal();
}
const GEMINI_ID="gemini:gemini-3.6-flash";
const GEMINI_NOTICE="Google Gemini로 이 대화·공개 논문 근거와 직접 선택해 보내는 이미지를 전송합니다. 등록된 개인 프로필·문서·링크·다른 대화의 첨부는 제외됩니다. 민감정보가 담긴 이미지는 보내지 마세요. 프로필 작업은 새 대화에서 다른 모델을 선택해 주세요.";
const CLIPBOARD_IMAGE_TYPES={"image/png":"png","image/jpeg":"jpg","image/webp":"webp"};
let pastedImageNumber=0;
function explicitImageAttachment(item){
 if(!item||typeof item!=="object"||item.source_url||item.source)return false;
 return item.file?!!CLIPBOARD_IMAGE_TYPES[item.file.type]||(!item.file.type&&/\.(png|jpe?g|webp)$/i.test(item.file.name)):item.kind==="image";
}
function clipboardImages(event){
 const data=event.clipboardData;if(!data)return [];
 const items=Array.from(data.items||[]);
 const supplied=items.length?items.filter(item=>item.kind==="file").map(item=>item.getAsFile()).filter(Boolean):Array.from(data.files||[]);
 const images=[...new Set(supplied)].filter(file=>file.type.startsWith("image/"));
 if(images.some(file=>!CLIPBOARD_IMAGE_TYPES[file.type]))throw new Error("붙여넣기는 PNG, JPEG, WebP 이미지를 지원합니다.");
 return images.map(file=>{
  const suffix=CLIPBOARD_IMAGE_TYPES[file.type],matches=suffix==="jpg"?/\.jpe?g$/i.test(file.name):file.name?.toLowerCase().endsWith("."+suffix);
  return matches&&file.name.length<=240?file:new File([file],"붙여넣은-이미지-"+(++pastedImageNumber)+"."+suffix,{type:file.type,lastModified:file.lastModified});
 });
}
function pasteImages(event){
 if(event.isTrusted===false)return;
 try{
  const images=clipboardImages(event);if(!images.length)return;
  if(composerSendLocked()){error("이미지는 응답 처리가 끝난 뒤 붙여넣어 주세요. 작성 중인 글은 유지됩니다.");return;}
  upload(images);
 }catch(e){error(e.message);}
 // Keep the browser's native plain-text/caret/IME insertion and input event.
}
function isGeminiModel(id=selectedModel){return id===GEMINI_ID;}
function hasGeminiScope(saved){const scope=saved?.provider_scope;return ["gemini_public_papers.v1","gemini_public_papers.v2"].includes(scope?.id)&&scope.provider==="gemini"&&scope.model_id===GEMINI_ID;}
function isGeminiSession(saved=session){return hasGeminiScope(saved)||isGeminiModel(saved?.model_id);}
function isRuntimeModel(id=selectedModel){return id==="runtime"&&["codex_oauth","openai_api"].includes(catalog.find(m=>m.id===id)?.provider);}
function isScopedBridgeModel(id=selectedModel){const model=catalog.find(m=>m.id===id);return id==="bridge"&&model?.provider==="bridge"&&model.public_scope===true;}
function hasRuntimeScope(saved){const scope=saved?.provider_scope;return (["runtime_public_papers.v1","runtime_public_papers.v2"].includes(scope?.id)&&["codex_oauth","openai_api"].includes(scope.provider)&&scope.model_id==="runtime")||(scope?.id==="runtime_public_papers.v2"&&scope.provider==="bridge"&&scope.model_id==="bridge");}
function hasPublicPaperScope(saved){return hasGeminiScope(saved)||hasRuntimeScope(saved);}
function isPublicPaperModel(id=selectedModel){return isGeminiModel(id)||isRuntimeModel(id)||isScopedBridgeModel(id);}
function isPublicPaperContext(id=selectedModel,saved=session){return hasPublicPaperScope(saved)||isPublicPaperModel(id);}
function allowsScopedImages(id=selectedModel,saved=session){return (saved?.id?(hasGeminiScope(saved)||(hasRuntimeScope(saved)&&saved.provider_scope.id==="runtime_public_papers.v2"&&["codex_oauth","openai_api"].includes(saved.provider_scope.provider))):(isGeminiModel(id)||isRuntimeModel(id)))&&catalog.find(m=>m.id===id)?.vision===true;}
function isPublicPaperSession(saved=session){return hasPublicPaperScope(saved)||isGeminiModel(saved?.model_id)||saved?.model_id==="runtime";}
function allowsScopedDocuments(id=selectedModel,saved=session){return isPublicPaperContext(id,saved)&&(!saved?.id||(hasPublicPaperScope(saved)&&["gemini_public_papers.v2","runtime_public_papers.v2"].includes(saved.provider_scope.id)));}
function explicitScopedAttachment(item,id,saved){
 if(!item||typeof item!=="object")return false;
 if(!allowsScopedDocuments(id,saved))return allowsScopedImages(id,saved)&&explicitImageAttachment(item);
 if(item.source_url)return /^https:\/\//i.test(item.source_url);
 if(item.kind==="document")return true;
 if(item.file&&!explicitImageAttachment(item))return /\.(txt|md|csv|json|log|pdf|docx|pptx|html?|htm)$/i.test(item.file.name);
 return allowsScopedImages(id,saved)&&explicitImageAttachment(item);
}
function blocksScopedLinks(){return isPublicPaperContext()&&!allowsScopedDocuments();}
function modelExecutionLabel(id=selectedModel){
 const model=catalog.find(m=>m.id===id),name=model?.name||id||"선택한 모델";
 if(model?.provider==="bridge")return "운영자 PC의 "+name;
 if(model?.local||model?.provider==="ollama")return "이 기기의 "+name;
 if(model?.provider==="guide")return "이 서비스의 "+name+" (AI 미사용)";
 const provider={gemini:"Google Gemini",openai:"OpenAI API",openai_api:"OpenAI API",codex_oauth:"Codex 연결"}[model?.provider];
 return (provider||"선택한 연결")+"의 "+name;
}
function publicPaperNotice(){return modelExecutionLabel()+"로 이 대화와 공개 논문 근거"+(allowsScopedDocuments()?", 직접 선택해 보낸 문서의 추출 본문·출처":"")+"를 전송합니다. 등록된 개인 프로필·다른 대화의 자료는 포함하지 않습니다. "+(allowsScopedDocuments()?"일부만 추출된 자료는 표시된 범위만 읽습니다. ":"문서·링크는 이 대화에 추가하지 않습니다. ")+(allowsScopedImages()?"직접 선택한 이미지도 전송됩니다. ":"이미지는 이 선택에서 지원하지 않습니다. ")+"민감정보 전송에 유의해 주세요. 프로필 작업은 새 대화를 이용해 주세요.";}
function publicPaperLabel(saved){return catalog.find(m=>m.id===saved?.model_id)?.name||"선택한 모델";}
function modelBoundaryMessage(id,attached=files,saved=session,turnId=null){
 if(saved?.id&&isPublicPaperModel(id)&&!hasPublicPaperScope(saved))return "이 대화의 자료 범위는 바꿀 수 없어요. ‘새 대화’를 누른 뒤 사용할 모델을 선택해 주세요.";
 if(isPublicPaperContext(id,saved)&&attached.some(item=>{if(typeof item==="string"){const prior=saved?.messages?.find(m=>m.role==="user"&&m.turn_id===turnId);item=(prior?prior.attachments||[]:files).find(f=>f.id===item);}return !explicitScopedAttachment(item,id,saved);} ))return allowsScopedDocuments(id,saved)?"직접 선택해 업로드한 지원 자료만 보낼 수 있어요. 이미지 지원 여부도 확인해 주세요.":"이전 대화의 첨부 범위는 유지됩니다. 문서·링크는 새 대화에서 선택해 주세요.";
 return "";
}
function selectModel(id){
 const chosen=catalog.find(m=>m.id===id);
 if(!chosen?.enabled){$("modelSelect").value=selectedModel;if(chosen?.provider==="bridge"){toast("이 Gemma는 연결 대기 중입니다. 사용 가능한 모델을 선택해 주세요.");return;}if(isPublicPaperModel(id)){error("외부 모델 연결을 지금 사용할 수 없어요. 설정이 준비된 뒤 새 대화에서 선택해 주세요.");return;}$("provider").value=chosen?.provider||"openai";modal("settingsDialog");return;}
 const boundary=modelBoundaryMessage(id);if(boundary){$("modelSelect").value=selectedModel;error(boundary);return;}
 selectedModel=chosen.id;modelSelectionOrigin="explicit";modelSelectionEpoch++;controls();error();render();
}
function option(){return catalog.find(m=>m.id===selectedModel);}
function selectedRequestModel(){if(!option()?.enabled)throw new Error("선택한 모델을 지금 사용할 수 없어요. 사용 가능한 모델을 선택해 주세요.");return {model_id:selectedModel,model_selection_origin:selectionOrigin(modelSelectionOrigin)};}
function modelSelectionNotice(){return session?.id&&selectedModel!==session.model_id?"모델 변경은 다음 요청에서 확인합니다. 이 대화의 자료 범위는 유지됩니다. ":"";}
function canRetryMessage(message,saved=session){
 if(!message)return false;
 if(message.retry_available!==false)return true;
 const latestUser=saved?.messages?.findLast(m=>m.role==="user"),latestAssistant=saved?.messages?.findLast(m=>m.role==="assistant");
 return saved?.model_switch_retry_available===true&&message.status==="error"&&message.turn_id===latestUser?.turn_id&&message.turn_id===latestAssistant?.turn_id&&modelSelectionOrigin==="explicit"&&selectedModel!==saved.model_id&&option()?.enabled===true;
}
function retryButtonLabel(message){
 const name=busy&&retryDisplay?.turn_id===message.turn_id?retryDisplay.name:option()?.name||selectedModel||"선택한 모델";
 return name+"로 다시 시도";
}
function responseModelLabel(message){return message.source==="guide"?"기록 탐색 안내 · AI 미사용":message.model||"수소문";}
function selectionOrigin(value){return ["automatic","explicit","legacy_unknown"].includes(value)?value:"legacy_unknown";}
function resolveModelSelection(models,defaultId,id,origin){
 origin=selectionOrigin(origin);
 if(session?.id&&id===session.model_id)return {id,origin};
 if(id&&origin!=="automatic")return {id,origin};
 const enabled=value=>models.some(m=>m.id===value&&m.enabled),next=enabled(defaultId)?defaultId:models.find(m=>m.enabled)?.id||"";
 if(id&&enabled(id)&&id!=="guide")return {id,origin:"automatic"};
 return {id:next,origin:"automatic"};
}
function renderModelSelect(){
 const missing=selectedModel&&!catalog.some(m=>m.id===selectedModel)?'<option value="'+esc(selectedModel)+'" selected disabled>'+esc(selectedModel)+' · 연결 불가</option>':"";
 $("modelSelect").innerHTML=missing+catalog.map(m=>'<option value="'+esc(m.id)+'"'+(m.id===selectedModel?' selected':'')+(!m.enabled&&m.provider==="bridge"?' disabled':'')+'>'+esc(m.provider==="ollama"?m.name+" · 로컬":m.name)+'</option>').join("")||'<option value="">연결할 모델 없음</option>';
 $("modelSelect").value=selectedModel;
}
function syncModelSelection(){
 if(busy||profileBusy||prepareBusy||uploading)return;
 const next=resolveModelSelection(catalog,modelDefault,selectedModel,modelSelectionOrigin);
 if(next.id!==selectedModel||next.origin!==modelSelectionOrigin){selectedModel=next.id;modelSelectionOrigin=next.origin;renderModelSelect();}
}
function restoreModelSelection(saved,epoch=modelSelectionEpoch){
 if(epoch!==modelSelectionEpoch||typeof saved?.model_id!=="string"||!saved.model_id)return;
 selectedModel=saved.model_id;modelSelectionOrigin=selectionOrigin(saved.model_selection_origin);modelSelectionEpoch++;
 syncModelSelection();renderModelSelect();
}
function modelOptions(data){
 publicMode=!!data.public;
 if(publicMode){$("configForm").hidden=true;$("localStatus").closest(".local-status").querySelector("small").textContent="대화와 제안은 방문자별로 분리됩니다. 무료 시연 기록은 서버 재시작 때 사라질 수 있습니다.";$("letterDialog").querySelector("p.subtle").textContent="이 방문자의 제안함에 시연 기록으로 저장됩니다. 실제 수신자에게 연락하지 않습니다.";}
 catalog=data.models;modelDefault=data.default||"";syncModelSelection();renderModelSelect();
 $("localStatus").textContent=publicMode?"공개 서비스 · 방문자별 대화":catalog.filter(m=>m.local).length?"Ollama · 설치 모델 "+catalog.filter(m=>m.local).length+"개":"Ollama에 연결할 수 없어요";controls();
}
async function refreshModelOptions(path="/api/chat/models?refresh=1"){
 const ticket=++modelCatalogTicket,data=await api(path);
 if(ticket!==modelCatalogTicket)return false;
 modelOptions(data);return true;
}
function controls(){syncModelSelection();const m=option(),locked=composerSendLocked(),navigationLocked=composerClientLocked(),profileIntent=profileUI?.shouldHandle($("message").value);if(publicMode){$("settingsDialog").querySelector("p.subtle").textContent=m?.id==="runtime"&&m.provider==="codex_oauth"?"Codex OAuth로 "+(m.name||"선택한 모델")+" 모델을 사용합니다. 연결에 실패하면 오류를 안내하며 기록 탐색으로 자동 전환하지 않습니다.":"운영자가 연결한 모델을 사용합니다. AI 미연결 시 기록 탐색 안내만 제공됩니다.";}$("sendButton").disabled=locked||uploading||(!m?.enabled&&!profileIntent)||(!$("message").value.trim()&&!files.length);$("sendButton").hidden=busy;$("stopButton").hidden=!busy;$("modelSelect").disabled=locked;$("attachButton").disabled=locked||uploading||(isPublicPaperContext()&&!allowsScopedDocuments()&&!allowsScopedImages());$("attachmentCancel").hidden=!uploading;$("attachmentCancel").disabled=!uploading;$("attachmentProgress").hidden=!uploading;$("attachmentProgress").textContent=uploading?attachmentStatus:"";$("attachmentList").setAttribute("aria-busy",String(uploading));$("attachmentList").querySelectorAll('[data-action="remove-file"]').forEach(button=>button.disabled=locked);$("message").disabled=accountNavigationPending||accountInvalidated||profileBusy||uploading;$("newButton").disabled=navigationLocked;$("historyButton").disabled=navigationLocked;$("settingsButton").disabled=locked;$("profileButton").disabled=locked||isPublicPaperContext();$("profileButton").setAttribute("aria-expanded",String(!!profileUI?.isOpen()));$("modelHint").textContent=modelSelectionNotice()+(isPublicPaperContext()?publicPaperNotice():profileIntent?"내 프로필에서 처리합니다. 모델에는 전송하지 않습니다.":uploading?"첨부파일을 전송하고 있어요…":(selectedModel&&!m?.enabled)?"선택한 모델을 지금 사용할 수 없어요. 연결 상태를 확인하거나 다른 모델을 선택해 주세요.":m?.provider==="guide"?"기록 탐색 안내 · AI를 사용하지 않습니다.":m?.provider==="bridge"?"운영자 PC의 Gemma로 이 대화와 첨부 내용을 처리합니다.":m?.local?"이 기기의 모델과 대화합니다.":m?.enabled?"선택한 API로 이 대화와 첨부 내용을 전송합니다.":"설정에서 모델을 연결해 주세요.");syncDiscoveryControls();updateBriefNotice();renderRecoveryControl();renderRegisteredExperts();}
const ATTACHMENT_MAX_BYTES=10*1024*1024,ATTACHMENT_TIMEOUT_MS=45000;
const ATTACHMENT_CHUNK_THRESHOLD=2*1024*1024,ATTACHMENT_CHUNK_BYTES=524288,ATTACHMENT_TOTAL_TIMEOUT_MS=240000;
let attachmentTransfer=null,attachmentStatus="",attachmentPreviewTicket=0;
function pendingAttachment(item){return !!(item.file||item.source_url);}
function attachmentSummary(item){
 if(pendingAttachment(item))return "전송 대기";
 return item.truncated||item.extraction?.status==="partial"?"일부만 읽음":"자료 준비됨";
}
function attachmentBatchIssue(list){
 if(files.length+list.length>4)return "파일과 링크는 합쳐서 한 번에 4개까지 첨부할 수 있어요.";
 const rejected=[];
 for(const file of list){
  let reason="";
  if(!file.name||file.name.length>240)reason="파일 이름을 확인해 주세요";
  else if(!/\.(txt|md|csv|json|log|pdf|docx|pptx|html?|htm|png|jpe?g|webp)$/i.test(file.name))reason="지원하지 않는 형식";
  else if(!Number.isSafeInteger(file.size)||file.size<=0)reason="빈 파일";
  else if(file.size>ATTACHMENT_MAX_BYTES)reason="10MiB 초과";
  if(reason)rejected.push(file.name+" · "+reason);
 }
 return rejected.length?"이번 선택은 추가하지 않았어요: "+rejected.join(" / "):"";
}
function documentUrl(value){
 const raw=String(value||"").trim();if(!raw||raw.length>2048||/[\u0000-\u0020\u007f]/.test(raw))return null;
 try{const url=new URL(raw);return url.protocol==="https:"&&!url.username&&!url.password&&!url.hash&&(!url.port||url.port==="443")?raw:null;}catch{return null;}
}
// Only explicit composer submission reads URLs; typing never starts a request.
let inlineMessageLinks=new Map();
function normalizeMessageDocumentUrl(value){
 const raw=String(value||"").trim();
 if(!raw||raw.length>2048||/[\u0000-\u0020\u007f\\]/.test(raw))return null;
 try{
  const url=new URL(raw);
  if(url.protocol!=="https:"||!url.hostname||url.username||url.password||url.port&&url.port!=="443")return null;
  url.hash="";
  return documentUrl(url.href);
 }catch{return null;}
}
function messageDocumentUrls(text){
 const urls=[],seen=new Set(),raw=String(text||""),pattern=/https?:\/\//gi;
 let match;
 while((match=pattern.exec(raw))){
  let end=pattern.lastIndex;const depth={"(":0,"[":0,"{":0},opening={")":"(","]":"[","}":"{"};
  // Unmatched closers belong to prose/Markdown; balanced DOI parentheses stay intact.
  while(end<raw.length&&!/[\s<>"'`|]/.test(raw[end])){
   const char=raw[end];
   if(Object.hasOwn(depth,char))depth[char]++;
   else if(opening[char]){if(!depth[opening[char]])break;depth[opening[char]]--;}
   end++;
  }
  pattern.lastIndex=end;
  const value=raw.slice(match.index,end).replace(/[.,;:!?\u3002\uff0c\uff1b\uff1a\uff01\uff1f\u2026\u2019\u201d]+$/u,"");
  const url=normalizeMessageDocumentUrl(value);
  if(!url)throw new Error("본문의 링크는 인증정보가 없는 공개 HTTPS 문서 주소여야 해요. 주소를 확인해 주세요. 작성한 글과 선택한 파일은 남아 있어요.");
  if(!seen.has(url)){seen.add(url);urls.push(url);}
 }
 return urls;
}
function inlineAttachmentUrls(item,trackedUrl){
 return [...new Set([trackedUrl,item?.source_url,item?.source?.original_url,item?.source?.final_url].map(normalizeMessageDocumentUrl).filter(Boolean))];
}
function planInlineMessageAttachments(text,items,tracked,makeId){
 const urls=messageDocumentUrls(text),wanted=new Set(urls),autoLinks=new Map();
 const kept=items.filter(item=>!tracked.has(item.id)||inlineAttachmentUrls(item,tracked.get(item.id)).some(url=>wanted.has(url)));
 const known=new Set();
 for(const item of kept){
  if(tracked.has(item.id))autoLinks.set(item.id,tracked.get(item.id));
  for(const url of inlineAttachmentUrls(item,tracked.get(item.id)))known.add(url);
 }
 const added=urls.filter(url=>!known.has(url));
 if(kept.length+added.length>4)throw new Error("파일과 본문 링크는 합쳐서 한 번에 4개까지 첨부할 수 있어요. 작성한 글과 선택한 파일은 남아 있어요.");
 const planned=[...kept];
 for(const url of added){const id=makeId();planned.push({id,name:url,source_url:url});autoLinks.set(id,url);}
 return {files:planned,autoLinks,urls};
}
function acceptInlineAttachment(previous,uploaded){
 const url=inlineMessageLinks.get(previous.id);
 if(url){inlineMessageLinks.delete(previous.id);inlineMessageLinks.set(uploaded.id,url);}
}
function abortAttachment(){cancelAttachmentClientReports();if(attachmentTransfer){attachmentTransfer.cancelled=true;attachmentTransfer.controller?.abort();}}
function attachmentAbortError(){const error=new Error("첨부 처리를 중지했어요.");error.name="AbortError";return error;}
function withAttachmentAbort(work,signal){
 if(signal.aborted)return Promise.reject(attachmentAbortError());
 return new Promise((resolve,reject)=>{
  const stop=()=>reject(attachmentAbortError());signal.addEventListener("abort",stop,{once:true});
  Promise.resolve(work).then(resolve,reject).finally(()=>signal.removeEventListener("abort",stop));
 });
}
function requireAttachmentTransfer(transfer){
 if(attachmentTransfer!==transfer||transfer.cancelled||accountNavigationPending||accountInvalidated)throw attachmentAbortError();
}
async function attachmentStep(path,body,transfer,signal){
 requireAttachmentTransfer(transfer);if(signal.aborted)throw attachmentAbortError();
 const aborter=new AbortController(),stop=()=>aborter.abort();let timedOut=false;
 signal.addEventListener("abort",stop,{once:true});
 const timer=setTimeout(()=>{timedOut=true;aborter.abort();},ATTACHMENT_TIMEOUT_MS);
 try{return await withAttachmentAbort(api(path,body,aborter.signal),aborter.signal);}
 catch(error){if(timedOut){const failure=new Error("한 전송 요청의 45초 제한을 넘었어요. 자동 재전송하지 않습니다.");failure.code="attachment_request_timeout";throw failure;}throw error;}
 finally{clearTimeout(timer);signal.removeEventListener("abort",stop);aborter.abort();}
}
function attachmentChunkBase64(bytes){
 let binary="";for(let offset=0;offset<bytes.length;offset+=8192)binary+=String.fromCharCode(...bytes.subarray(offset,offset+8192));
 return btoa(binary);
}
async function transmitChunkedAttachment(item,transfer,signal,deadline){
 const ownerToken=token;let uploadId=null,completing=false;
 const requireCurrent=()=>{requireAttachmentTransfer(transfer);if(signal.aborted||token!==ownerToken)throw attachmentAbortError();};
 try{
  requireCurrent();
  if(!Number.isSafeInteger(item.file.size)||item.file.size<=0||item.file.size>ATTACHMENT_MAX_BYTES)throw new Error("파일은 10MiB 이하로 첨부해 주세요.");
  if(!crypto.subtle)throw new Error("이 브라우저에서 파일 무결성 확인을 사용할 수 없어요.");
  const raw=await withAttachmentAbort(item.file.arrayBuffer(),signal);requireCurrent();
  if(raw.byteLength!==item.file.size)throw new Error("파일 크기를 확인하지 못했어요.");
  const digest=await withAttachmentAbort(crypto.subtle.digest("SHA-256",raw),signal);requireCurrent();
  const sha256=Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,"0")).join("");
  const count=Math.ceil(raw.byteLength/ATTACHMENT_CHUNK_BYTES);
  const begin=await attachmentStep("/api/attachments/begin",{name:item.name,size:raw.byteLength,sha256},transfer,signal);
  if(typeof begin?.upload_id==="string"&&/^[a-f0-9]{32}$/.test(begin.upload_id))uploadId=begin.upload_id;
  requireCurrent();
  if(!uploadId||begin.chunk_bytes!==ATTACHMENT_CHUNK_BYTES||begin.chunk_count!==count||begin.expires_in!==600)throw new Error("파일 분할 전송 설정을 확인하지 못했어요.");
  for(let index=0;index<count;index++){
   requireCurrent();
   attachmentStatus=item.name+" · 나누어 보내고 있어요 ("+(index+1)+"/"+count+") · 요청당 45초, 파일당 최대 4분";controls();
   const offset=index*ATTACHMENT_CHUNK_BYTES,data=attachmentChunkBase64(new Uint8Array(raw,offset,Math.min(ATTACHMENT_CHUNK_BYTES,raw.byteLength-offset)));
   const received=await attachmentStep("/api/attachments/chunk",{upload_id:uploadId,index,data},transfer,signal);requireCurrent();
   if(received?.upload_id!==uploadId||received.index!==index||received.received!==true)throw new Error("파일 조각의 전송 결과를 확인하지 못했어요.");
  }
  requireCurrent();attachmentStatus=item.name+" · 전송한 자료를 읽고 있어요…";controls();
  // Once complete is attempted, its outcome may be unknown. Never retry or cancel it.
  completing=true;return await attachmentStep("/api/attachments/complete",{upload_id:uploadId},transfer,signal);
 }catch(error){
  if(uploadId&&!completing&&token===ownerToken&&!accountNavigationPending&&!accountInvalidated&&attachmentTransfer===transfer){
   const remaining=Math.min(5000,deadline-Date.now());
   if(remaining>0){
    const cleanup=new AbortController(),timer=setTimeout(()=>cleanup.abort(),remaining);
    try{await withAttachmentAbort(api("/api/attachments/cancel",{upload_id:uploadId},cleanup.signal),cleanup.signal);}catch{}finally{clearTimeout(timer);cleanup.abort();}
   }
  }
  throw error;
 }
}
async function transmitAttachment(item,transfer,index,total){
 requireAttachmentTransfer(transfer);
 const chunked=publicMode&&!item.source_url&&item.file?.size>ATTACHMENT_CHUNK_THRESHOLD;
 const limit=chunked?ATTACHMENT_TOTAL_TIMEOUT_MS:ATTACHMENT_TIMEOUT_MS,deadline=Date.now()+limit;
 const aborter=new AbortController();transfer.controller=aborter;let timedOut=false;
 attachmentStatus=item.name+" · 자료를 보내고 읽고 있어요… ("+index+"/"+total+")";controls();
 const timer=setTimeout(()=>{timedOut=true;aborter.abort();},limit);
 try{
  const work=async()=>{
   if(item.source_url)return api("/api/attachments/https",{url:item.source_url},aborter.signal);
   if(chunked)return transmitChunkedAttachment(item,transfer,aborter.signal,deadline);
   const data=await dataUrl(item.file,aborter.signal);requireAttachmentTransfer(transfer);
   if(aborter.signal.aborted)throw attachmentAbortError();
   return api("/api/attachments",{name:item.name,data},aborter.signal);
  };
  const value=await withAttachmentAbort(work(),aborter.signal);requireAttachmentTransfer(transfer);
  if(!value||typeof value.id!=="string"||!/^[a-f0-9]{32}$/.test(value.id)||typeof value.name!=="string")throw new Error("첨부 처리 결과를 확인하지 못했어요.");
  return value;
 }catch(error){
  const message=timedOut?(chunked?"파일 전송의 전체 4분 제한을 넘었어요.":"45초 안에 처리 결과를 확인하지 못했어요.")+" 작성한 글과 선택은 남아 있어요. 서버에 저장됐을 수 있으며 자동 재전송하지 않습니다.":error.name==="AbortError"?"첨부 처리를 취소했어요. 작성한 글과 선택은 남아 있어요. 서버의 저장 취소나 삭제는 보장되지 않습니다.":error.message;
  const failure=new Error(item.name+" · "+message);
  for(const key of ["status","code","requestId","retry_available"])if(error[key]!==undefined)failure[key]=error[key];
  throw failure;
 }finally{clearTimeout(timer);aborter.abort();if(transfer.controller===aborter)transfer.controller=null;}
}
function removeAttachment(id){
 if(composerSendLocked())return;
 const index=files.findIndex(f=>f.id===id);files=files.filter(f=>f.id!==id);renderFiles();
 const next=files[Math.min(Math.max(0,index),files.length-1)];
 const target=next?Array.from($("attachmentList").querySelectorAll('[data-action="preview-file"]')).find(b=>b.dataset.id===next.id):null;
 (target||$("attachButton")).focus();
}
function attachmentPreviewInfo(item){
 if(item.kind==="image")return "이미지 지원 모델에서만 대화에 사용할 수 있어요.";
 const extraction=item.extraction,unit={page:"쪽",slide:"슬라이드",paragraph:"문단",line:"줄"}[extraction?.unit];
 let note="읽은 텍스트 "+Number(item.characters||0).toLocaleString()+"자";
 if(unit&&Number.isSafeInteger(extraction.processed_units)&&Number.isSafeInteger(extraction.total_units))note+=" · "+extraction.processed_units+"/"+extraction.total_units+unit+" 처리";
 if(item.truncated||extraction?.status==="partial")note+=" · 일부만 읽음 · 전체 문서를 확인하지 못했어요";
 const limits=Array.isArray(extraction?.limits)?extraction.limits:[];
 if(limits.includes("math_structure"))note+=" · 수식의 글자는 읽었지만 배치·연산 구조는 일부 보존되지 않았어요";
 if(limits.includes("text_limit"))note+=" · 텍스트 길이 제한에 도달했어요";
 if(limits.some(limit=>["page_limit","slide_limit","paragraph_limit","line_limit"].includes(limit)))note+=" · 문서 처리 개수 제한에 도달했어요";
 return note;
}
function attachmentPreviewHTML(item){
 const source=item.source,original=documentUrl(source?.original_url),final=documentUrl(source?.final_url);
 let html=original?'<p class="attachment-source">원 URL: <a href="'+esc(original)+'" target="_blank" rel="noopener noreferrer">'+esc(original)+'</a>'+(final&&final!==original?'<br>최종 URL: <a href="'+esc(final)+'" target="_blank" rel="noopener noreferrer">'+esc(final)+'</a>':"")+(typeof source?.acquired_at==="string"?'<br>가져온 시각: '+esc(source.acquired_at):"")+'<br>외부 제공 자료 · 내용의 사실성은 확인되지 않았어요.</p>':"";
 if(item.image&&["image/png","image/jpeg","image/webp"].includes(item.mime))return html+'<img alt="첨부 이미지" src="data:'+item.mime+';base64,'+esc(item.image)+'">';
 const text=typeof item.text==="string"?item.text:"",labels={page:"페이지",slide:"슬라이드",paragraph:"문단",line:"줄"};
 const characters=Array.from(text); // Server offsets count Unicode code points.
 const spans=(Array.isArray(item.source_spans)?item.source_spans:[]).filter(s=>labels[s.kind]&&Number.isSafeInteger(s.index)&&s.index>0&&Number.isSafeInteger(s.start)&&Number.isSafeInteger(s.end)&&s.start>=0&&s.start<s.end&&s.end<=characters.length).slice(0,1000);
 if(spans.length)html+='<details class="attachment-locations"><summary>추출 위치 '+spans.length+'개 보기</summary>'+spans.map(s=>'<details><summary>'+labels[s.kind]+' '+s.index+'</summary><pre>'+esc(characters.slice(s.start,s.end).join(""))+'</pre></details>').join("")+'</details>';
 return html+'<pre>'+esc(text)+'</pre>';
}
async function previewAttachment(id,opener){
 const ticket=++attachmentPreviewTicket,pending=files.find(f=>f.id===id&&pendingAttachment(f));
 if(pending){
  if(pending.file&&CLIPBOARD_IMAGE_TYPES[pending.file.type]){
   let data;try{data=await dataUrl(pending.file);}catch(e){if(ticket===attachmentPreviewTicket&&!accountNavigationPending&&!accountInvalidated)throw e;return;}
   if(ticket!==attachmentPreviewTicket||accountNavigationPending||accountInvalidated||!files.includes(pending))return;
   $("fileTitle").textContent=pending.name;$("fileInfo").textContent="내 기기의 이미지 미리보기 · 아직 전송하지 않았어요.";
   $("filePreview").innerHTML='<img alt="전송 대기 이미지" src="data:'+pending.file.type+';base64,'+esc(data)+'">';modal("fileDialog",opener);return;
  }
  $("fileTitle").textContent=pending.name;$("fileInfo").textContent="전송 대기 · 메시지를 보낼 때 자료를 가져오고 읽습니다.";$("filePreview").textContent=pending.source_url?"원 URL: "+pending.source_url+"\n아직 링크 내용을 읽지 않았어요.":"파일 크기: "+pending.file.size.toLocaleString()+" bytes";modal("fileDialog",opener);return;
 }
 let item;try{item=await api("/api/attachment?id="+encodeURIComponent(id));}
 catch(e){if(ticket===attachmentPreviewTicket&&!accountNavigationPending&&!accountInvalidated)throw e;return;}
 if(ticket!==attachmentPreviewTicket||accountNavigationPending||accountInvalidated)return;
 $("fileTitle").textContent=item.name;$("fileInfo").textContent=attachmentPreviewInfo(item);$("filePreview").innerHTML=attachmentPreviewHTML(item);modal("fileDialog",opener);
}

function resizeInput(){$("message").style.height="auto";$("message").style.height=Math.min(200,$("message").scrollHeight)+"px";controls();}
function fileChips(items,removable=false){return items.map(f=>'<span class="file-chip"><button type="button" data-action="preview-file" data-id="'+esc(f.id)+'" title="첨부 자료 확인">▤ '+esc(f.name)+' <small>'+esc(attachmentSummary(f))+'</small></button>'+(removable?'<button type="button" class="remove" data-action="remove-file" data-id="'+esc(f.id)+'" aria-label="'+esc(f.name)+' 첨부 제거">×</button>':"")+'</span>').join("");}
function renderFiles(){$("attachmentList").hidden=!files.length;$("attachmentList").innerHTML=fileChips(files,true);controls();}
function scrollBottom(){if(autoScroll)requestAnimationFrame(()=>{if(autoScroll&&!briefEditor)window.scrollTo({top:document.documentElement.scrollHeight,behavior:"instant"});});}
// lookup_ready and summary/question describe server-compiled search clues.
// They do not assert that a candidate exists or that a proposal is ready.
function currentDiscovery(s=session){return !!s&&typeof s.id==="string"&&!!s.id&&s.search_context?.kind!=="stopped"&&typeof s.discovery?.lookup_ready==="boolean"&&typeof s.discovery.revision==="string"&&!!s.discovery.revision?s.discovery:null;}
function discoveryReady(s=session){return currentDiscovery(s)?.lookup_ready===true&&!s.pending;}
function discoveryCompletion(s=session){
 const discovery=currentDiscovery(s),result=s?.result;
 if(!discovery?.lookup_ready||s.pending||!s.ready||s.prepared_discovery_revision!==discovery.revision||s.search_context?.kind!=="recommend"||result?.intent!=="recommend"||result.inspection_only||result.historical_result||!Array.isArray(result.candidates))return "";
 const count=result.candidates.length;
 return count?"조회가 완료됐어요. 현재 조건으로 찾은 인물은 "+count+"명이에요.":"조회가 완료됐어요. 현재 조건으로 찾은 인물은 0명이에요.";
}
function recoverableScout(s=session){const r=s?.scout_recovery;return !!s?.id&&r?.available===true&&r.status==="required"&&typeof r.id==="string"&&typeof r.from_revision==="string"&&r.from_revision===s.request_spec?.revision&&s.request_spec?.state==="stale"&&briefHasContent(s.request_spec)&&!s.pending;}
function scoutButtonLabel(){return recoverableScout()?"이 정보로 다시 수소문하기":"이 정보로 수소문하기";}
function canPrepareDiscovery(){return (discoveryReady()&&briefCurrent()||recoverableScout())&&!briefEditor&&!briefFailure&&!busy&&!profileBusy&&!uploading&&!prepareBusy;}
function prepareProgressActive(){return prepareBusy&&prepareProgress?.ticket===prepareTicket&&prepareProgress.sessionId===session?.id&&!accountNavigationPending&&!accountInvalidated;}
function resetPrepareProgress(){prepareBusy=false;prepareProgress=null;}
function prepareProgressContent(){
 if(!prepareProgressActive())return "";
 const elapsed=Math.max(0,performance.now()-prepareProgress.started)%2400;
 return '<span class="avatar"><span class="susomun-ci susomun-ci--busy" style="--ci-busy-delay:-'+elapsed.toFixed(1)+'ms" aria-hidden="true"><span class="susomun-ci-h">H</span></span></span><span class="scout-prepare-label">수소문 응답을 기다리고 있어요.</span>';
}
function syncPrepareAnnouncement(active){
 // The brief may be replaced; one separate live node announces state changes only.
 let live=$("scoutPrepareLive");
 if(!live&&active){live=document.createElement("span");live.id="scoutPrepareLive";live.className="sr-only";live.setAttribute("role","status");live.setAttribute("aria-live","polite");live.setAttribute("aria-atomic","true");$("thread").before(live);}
 const label=active?"수소문 응답을 기다리고 있어요.":"";if(live&&live.textContent!==label)live.textContent=label;
}
function syncDiscoveryControls(){
 const active=prepareProgressActive();syncPrepareAnnouncement(active);
 const button=$("currentScoutButton"),scout=$("currentScout");if(!button||!scout)return;
 const available=!accountNavigationPending&&!accountInvalidated&&canPrepareDiscovery();scout.hidden=!(available||active);
 button.disabled=!available;button.textContent=active?"수소문 중…":scoutButtonLabel();
 button.setAttribute("aria-busy",String(active));
 const progress=$("scoutPrepareProgress");if(progress){progress.hidden=!active;progress.innerHTML=prepareProgressContent();}
}
function scoutCount(){
 const s=session?.scout,known=s?.count_status==="known"&&Number.isSafeInteger(s.count)&&s.count>=0;
 const label=known?(s.disclosed?"현재 공개된 인물 ":"관련 기록과 연결된 인물 ")+s.count+"명":"아직 인물 수를 확인하지 않았어요.";
 return '<p class="scout-count" role="status">'+esc(label)+(known&&!s.disclosed?'<small>기록 조회 기준 · 요청 적합성은 수소문 후 확인해요.</small>':'')+'</p>';
}
function scoutConditions(){
 const rows=session?.request_spec?.conditions||[];
 return rows.length?'<ul class="scout-conditions">'+rows.map(c=>'<li>'+esc((c.kind==='required'?'필수 · ':'선호 · ')+c.text)+'</li>').join('')+'</ul>':'';
}
function currentScout(){
 const available=!accountNavigationPending&&!accountInvalidated&&canPrepareDiscovery(),active=prepareProgressActive();
 return '<div class="continue-actions" id="currentScout"'+(available||active?'':' hidden')+'><button type="button" class="primary" id="currentScoutButton" data-action="prepare" title="등록된 인물과 근거를 조회합니다." aria-busy="'+String(active)+'"'+(available?'':' disabled')+'>'+(active?'수소문 중…':scoutButtonLabel())+'</button><div class="message-meta scout-prepare-progress" id="scoutPrepareProgress" aria-hidden="true"'+(active?'':' hidden')+'>'+prepareProgressContent()+'</div></div>';
}

// request_spec is the only accepted brief; this is an unsent editor buffer.
let briefSessionId=null,briefEditor=null,briefFailure=null,briefRenderKey="";
// Render-only signatures, never a second accepted request_spec or edit source.
let briefChangeAnchor=null,briefChangeLabel="";
const briefLabels={purposes:"목적",requested_help:"필요한 도움",conditions:"조건",open_questions:"아직 정하지 않은 점"};
const briefConditionLabel=kind=>({required:"필수",preference:"선호"}[kind]||String(kind||"조건"));
const briefRows=value=>Array.isArray(value)?value.filter(row=>row&&typeof row.text==="string"&&row.text.trim()):[];
// Preserve explicit user restrictions from accepted conditions without reclassifying them.
function briefConditionLines(value){
 const rows=briefRows(value),texts=new Set(rows.map(row=>row.text));
 const quotes=[...new Set(rows.map(row=>row.source_quote).filter(quote=>typeof quote==="string"&&quote.trim()))];
 return [...rows.map(row=>briefConditionLabel(row.kind)+" · "+row.text),...quotes.filter(quote=>!texts.has(quote)).map(quote=>"요청 원문 · "+quote)];
}
function briefFields(spec){
 return {purposes:briefRows(spec?.purposes).map(row=>row.text).join("\n"),requested_help:briefRows(spec?.requested_help).map(row=>row.text).join("\n"),conditions:briefConditionLines(spec?.conditions).join("\n"),open_questions:(Array.isArray(spec?.open_questions)?spec.open_questions:[]).filter(text=>typeof text==="string"&&text.trim()).join("\n")};
}
function briefHasContent(spec){return spec?.has_content===true&&[spec.purposes,spec.requested_help,spec.conditions].some(rows=>briefRows(rows).length>0);}
function briefRevisionCurrent(s=session){
 const spec=s?.request_spec,revision=spec?.revision;
 return !!s?.id&&spec?.state==="current"&&typeof revision==="string"&&!!revision&&revision===s.discovery?.revision&&revision===s.scout?.revision&&!s.pending;
}
function briefCurrent(s=session){return briefHasContent(s?.request_spec)&&briefRevisionCurrent(s);}
function briefState(){
 if(busy||session?.pending||session?.request_spec?.state==="updating")return "updating";
 if(session?.request_spec?.state==="stopped"||session?.scout?.status==="stopped")return "stopped";
 if(briefFailure?.sessionId===session?.id||session?.request_spec?.state==="failed")return "failed";
 return briefCurrent()?"current":"stale";
}
function ensureBriefHost(){
 let host=$("consultBriefHost");if(host)return host;
 host=document.createElement("section");host.id="consultBriefHost";host.className="consult-brief";host.hidden=true;host.setAttribute("aria-labelledby","consultBriefHeading");
 $("thread").after(host);
 host.addEventListener("click",event=>{
  const button=event.target.closest("button[data-brief-action]");if(!button||button.disabled)return;
  if(button.dataset.briefAction==="edit")openBriefEditor();
  if(button.dataset.briefAction==="stage")stageBriefCorrection();
  if(button.dataset.briefAction==="cancel"){
   if(briefEditor?.stagedText&&composerInputRevision===briefEditor.stagedComposerRevision&&$("message").value===briefEditor.stagedText)setComposerDraft(briefEditor.composerBefore);
   briefEditor=null;briefRenderKey="";renderBrief();resizeInput();controls();host.querySelector('[data-brief-action="edit"]')?.focus({preventScroll:true});
  }
 });
 host.addEventListener("input",event=>{
  if(event.target.id!=="consultBriefValue"||!briefEditor)return;
  briefEditor.values[briefEditor.field]=event.target.value;briefEditor.editVersion++;
  if(briefEditor.phase!=="pending")briefEditor.phase="editing";
  updateBriefNotice();syncDiscoveryControls();
 });
 host.addEventListener("change",event=>{
  if(event.target.id!=="consultBriefField"||!briefEditor)return;
  briefEditor.field=event.target.value;$("consultBriefValue").value=briefEditor.values[briefEditor.field];
  $("consultBriefValueLabel").textContent=briefLabels[briefEditor.field];
 });
 return host;
}

function briefStructureSignatures(spec){
 const texts=rows=>JSON.stringify(briefRows(rows).map(row=>row.text).sort());
 return {purposes:texts(spec?.purposes),requested_help:texts(spec?.requested_help),conditions:JSON.stringify(briefConditionLines(spec?.conditions).sort()),open_questions:JSON.stringify((Array.isArray(spec?.open_questions)?spec.open_questions:[]).filter(value=>typeof value==="string").slice().sort())};
}
function trackBriefStructuralChange(){
 const spec=session?.request_spec;
 if(busy||prepareBusy||briefFailure||!briefRevisionCurrent())return;
 if(!briefHasContent(spec)){briefChangeAnchor=null;briefChangeLabel="";return;}
 const completed=[...(session.messages||[])].reverse().find(message=>message.role==="assistant"&&message.status==="complete"&&message.kind!=="self_profile"&&message.audience!=="disclosed");
 if(!completed||typeof completed.turn_id!=="string"||typeof spec.source_turn_id!=="string"||!spec.source_turn_id)return;
 const signatures=briefStructureSignatures(spec),previous=briefChangeAnchor;
 if(!previous){briefChangeAnchor={sourceTurnId:spec.source_turn_id,completedTurnId:completed.turn_id,signatures};briefChangeLabel="";return;}
 const nextTurn=completed.turn_id!==previous.completedTurnId,newSource=spec.source_turn_id!==previous.sourceTurnId;
 if(nextTurn)briefChangeLabel="";
 if(newSource&&completed.turn_id===spec.source_turn_id){
  const changed=Object.keys(briefLabels).filter(key=>signatures[key]!==previous.signatures[key]);
  briefChangeLabel=changed.length?changed.map(key=>briefLabels[key]).join(" · ")+" 항목을 수정했어요.":"";
 }
 // Visible condition quotes count; other quote metadata, ordering and prepare revision alone do not.
 briefChangeAnchor={sourceTurnId:spec.source_turn_id,completedTurnId:completed.turn_id,signatures};
}
function newerAcceptedBriefForEditor(){
 const edit=briefEditor,spec=session?.request_spec;
 return !!edit&&edit.sessionId===session?.id&&!busy&&!briefFailure&&briefRevisionCurrent()&&typeof spec.source_turn_id==="string"&&!!spec.source_turn_id&&spec.source_turn_id!==edit.sourceTurnId&&(spec.source_revision||spec.revision)!==(edit.sourceRevision||edit.revision)&&session.messages?.some(message=>message.role==="assistant"&&message.turn_id===spec.source_turn_id&&message.status==="complete"&&message.kind!=="self_profile"&&message.audience!=="disclosed");
}

function updateBriefNotice(){
 const host=$("consultBriefHost");if(!host||host.hidden)return;
 const state=briefState(),editing=!!briefEditor,latestAccepted=newerAcceptedBriefForEditor();
 const text=state==="updating"?"이전 초안 · 새 내용을 반영하고 있어요.":state==="failed"?"이전 초안 · 변경을 반영하지 못했어요.":state==="stopped"?"수소문을 보류했어요.":editing?(latestAccepted?"새 초안이 도착했어요. 편집을 닫아 최신 내용을 확인하세요.":briefEditor.revision!==session?.request_spec?.revision?"이전 초안을 기준으로 편집 중이에요. 현재 대화와 함께 확인해 주세요.":briefEditor.phase==="staged"?"수정문을 입력창에 넣었어요. 확인한 뒤 보내기를 눌러 주세요.":"편집 중 · 아직 대화에 반영되지 않았어요."):state==="stale"?(session?.scout_recovery?.status==="unsupported"?"이전 검색 범위가 현재 자료에 없어 의뢰서 수정이 필요해요.":session?.request_spec?.stale_reason==="source_changed"?"등록 자료가 바뀌었어요. 의뢰서는 유지되며 같은 정보로 다시 수소문할 수 있어요.":"이전 초안 · 현재 대화에서 다시 확인해 주세요."):"대화에서 정리한 의뢰서 초안이에요.";
 host.querySelector(".consult-brief-status").textContent=text+(!editing&&state==="current"&&briefChangeLabel?" "+briefChangeLabel:"");
 const cancel=host.querySelector('[data-brief-action="cancel"]');if(cancel)cancel.textContent=latestAccepted?"편집 닫고 최신 초안 보기":"취소";
 const locked=busy||profileBusy||prepareBusy||uploading||!!session?.pending;
 host.querySelectorAll("[data-brief-action],#consultBriefField,#consultBriefValue").forEach(control=>{control.disabled=locked;});
 const stage=host.querySelector('[data-brief-action="stage"]');if(stage)stage.disabled=locked||!!profileUI?.isOpen();
}
function renderBrief(){
 const host=ensureBriefHost(),sid=session?.id||null,spec=session?.request_spec;
 if(sid!==briefSessionId){briefSessionId=sid;briefEditor=null;briefFailure=null;briefRenderKey="";briefChangeAnchor=null;briefChangeLabel="";host.replaceChildren();}
 if(briefFailure&&briefRevisionCurrent()&&(spec.revision!==briefFailure.revision||spec.source_turn_id!==briefFailure.sourceTurnId))briefFailure=null;
 if(briefEditor?.turnId&&!busy&&!session?.pending){
  const complete=briefEditor.editVersion===briefEditor.submittedVersion&&briefRevisionCurrent()&&spec.source_turn_id===briefEditor.turnId&&session.messages?.some(message=>message.role==="assistant"&&message.turn_id===briefEditor.turnId&&message.status==="complete");
  if(complete){briefEditor=null;briefFailure=null;briefRenderKey="";}
  else briefEditor.phase="failed";
 }
 trackBriefStructuralChange();
 const legacy=!!spec&&typeof spec.has_content!=="boolean"&&typeof spec.summary==="string"&&!!spec.summary.trim();
 host.hidden=!sid||(!briefHasContent(spec)&&!legacy&&!briefEditor);
 if(host.hidden){host.replaceChildren();briefRenderKey="";return;}
 if(briefEditor&&host.querySelector("#consultBriefEditor")){updateBriefNotice();syncDiscoveryControls();return;}
 const key=JSON.stringify([sid,spec]);
 if(key!==briefRenderKey){
  const fields=briefFields(spec),rows=Object.entries(fields).filter(([,value])=>value);
  host.innerHTML='<div class="consult-brief-heading"><h2 id="consultBriefHeading">의뢰서 초안</h2><button type="button" class="text-button" data-brief-action="edit">수정</button></div><p class="consult-brief-status" role="status"></p><dl class="consult-brief-fields">'+rows.map(([name,value])=>'<div><dt>'+esc(briefLabels[name])+'</dt><dd>'+esc(value)+'</dd></div>').join("")+'</dl>'+(legacy&&!rows.length?'<p class="consult-brief-legacy">'+esc(spec.summary)+'</p>':"")+(hasPublicPaperScope(session)?'<p class="small subtle">AI가 조회한 후보 수는 공개 논문 기준입니다. 등록 이력 조회와는 별도입니다.</p>':'')+currentScout();
  briefRenderKey=key;
 }
 updateBriefNotice();syncDiscoveryControls();
}
// Called only by explicit edit opening, never by brief refresh or input events.
function revealBriefEditorField(field){
 const rect=field.getBoundingClientRect(),viewport=window.visualViewport;
 const top=(viewport?.offsetTop||0)+16;
 let bottom=(viewport?.offsetTop||0)+(viewport?.height||window.innerHeight);
 const dock=document.querySelector(".composer-dock");
 if(dock){
  const position=getComputedStyle(dock).position,cover=dock.getBoundingClientRect();
  if((position==="sticky"||position==="fixed")&&cover.bottom>top&&cover.top<bottom&&cover.right>rect.left&&cover.left<rect.right)bottom=Math.min(bottom,cover.top);
 }
 bottom-=16;if(bottom<=top)return;
 const delta=rect.top<top||rect.height>bottom-top?rect.top-top:rect.bottom>bottom?rect.bottom-bottom:0;
 if(delta)window.scrollBy({top:delta,behavior:"instant"});
}
function openBriefEditor(){
 if(!session?.id||busy||profileBusy||prepareBusy||uploading||session.pending)return;
 const values=briefFields(session.request_spec);
 briefEditor={sessionId:session.id,revision:session.request_spec?.revision||null,sourceRevision:session.request_spec?.source_revision||null,sourceTurnId:session.request_spec?.source_turn_id||null,original:{...values},values:{...values},field:Object.keys(values).find(key=>values[key])||"purposes",phase:"editing",editVersion:0,submittedVersion:null,stagedText:null,composerBefore:"",turnId:null};
 const host=ensureBriefHost(),editor=document.createElement("div");editor.id="consultBriefEditor";editor.className="consult-brief-editor";
 editor.innerHTML='<label for="consultBriefField">고칠 항목</label><select id="consultBriefField">'+Object.entries(briefLabels).map(([key,label])=>'<option value="'+key+'"'+(key===briefEditor.field?' selected':'')+'>'+esc(label)+'</option>').join("")+'</select><label id="consultBriefValueLabel" for="consultBriefValue">'+esc(briefLabels[briefEditor.field])+'</label><textarea id="consultBriefValue" rows="3" maxlength="6000" aria-describedby="consultBriefEditHelp"></textarea><p id="consultBriefEditHelp">바꿀 항목만 고쳐 주세요. 내용을 비우면 그 항목을 지우는 요청으로 전달합니다. 조건의 필수·선호 구분도 함께 확인해 주세요.</p><div class="consult-brief-actions"><button type="button" class="secondary" data-brief-action="stage">입력창에 수정문 넣기</button><button type="button" class="text-button" data-brief-action="cancel">취소</button></div><p id="consultBriefEditError" role="alert" hidden></p>';
 host.querySelector('[data-brief-action="edit"]').hidden=true;host.insertBefore(editor,host.querySelector("#currentScout"));
 $("consultBriefValue").value=briefEditor.values[briefEditor.field];updateBriefNotice();syncDiscoveryControls();const field=$("consultBriefValue");field.focus({preventScroll:true});revealBriefEditorField(field);
}
function stageBriefCorrection(){
 const edit=briefEditor;if(!edit||edit.sessionId!==session?.id||busy||profileBusy||prepareBusy||uploading||session.pending||profileUI?.isOpen())return;
 const changed=Object.keys(briefLabels).filter(key=>edit.values[key]!==edit.original[key]);
 const failure=$("consultBriefEditError");failure.hidden=true;
 if(!changed.length){failure.textContent="바꾼 내용이 없어요.";failure.hidden=false;return;}
 const clearedAfterSubmission=!!edit.turnId&&!$("message").value;
 if(edit.stagedText&&$("message").value!==edit.stagedText&&!clearedAfterSubmission){failure.textContent="입력창의 수정문을 직접 고쳤어요. 그 내용을 먼저 보내거나, 편집을 취소한 뒤 다시 시작해 주세요.";failure.hidden=false;return;}
 const correction="의뢰서 수정 요청 (화면에서 편집한 내용)\n아래 항목만 변경하고, 나머지 목적과 조건은 유지해 주세요.\n\n"+changed.map(key=>"["+briefLabels[key]+"]\n기존: "+(edit.original[key]||"미기재")+"\n요청: "+(edit.values[key].trim()?edit.values[key]:"이 항목 삭제")).join("\n\n");
 const before=edit.stagedText?edit.composerBefore:$("message").value;
 const text=(before?before+"\n\n":"")+correction;
 if(text.length>$("message").maxLength){failure.textContent="수정문이 입력창의 허용 길이를 넘어요. 수정 내용을 줄여 주세요.";failure.hidden=false;return;}
 edit.composerBefore=before;edit.stagedText=text;edit.phase="staged";edit.turnId=null;
 setComposerDraft(text);edit.stagedComposerRevision=composerInputRevision;autoScroll=false;resizeInput();controls();updateBriefNotice();$("message").focus({preventScroll:true});
}
function beginBriefSubmission(payload){
 if(!briefEditor||briefEditor.sessionId!==payload.session_id||!briefEditor.stagedText)return null;
 const sameStaged=briefEditor.phase==="staged"&&payload.text===briefEditor.stagedText.trim();
 const sameRetry=briefEditor.phase==="failed"&&payload.text===briefEditor.submittedText;
 if(!sameStaged&&!sameRetry)return null;
 briefEditor.turnId=payload.turn_id;briefEditor.submittedText=payload.text;briefEditor.submittedVersion=briefEditor.editVersion;briefEditor.phase="pending";
 return briefEditor;
}
function failBriefSubmission(edit,sid){
 if(!session||session.id!==sid)return;
 briefFailure={sessionId:sid,revision:session.request_spec?.revision||null,sourceTurnId:session.request_spec?.source_turn_id||null};
 if(edit&&briefEditor===edit)edit.phase="failed";
}

async function prepareDiscovery(button,keyboard=false){
 if(!canPrepareDiscovery())return;
 let requested;try{requested=selectedRequestModel();}catch(e){error(e.message);return;}
 const boundary=modelBoundaryMessage(requested.model_id,[]);if(boundary){error(boundary);return;}
 const before=session,sid=before.id,recovery=recoverableScout(before)?before.scout_recovery:null,revision=recovery?.from_revision||before.discovery.revision,ticket=++prepareTicket;
 const current=()=>ticket===prepareTicket&&session===before&&session?.id===sid&&(recovery?session.scout_recovery?.id===recovery.id:session?.discovery?.revision===revision);
 const returnFocus=keyboard&&document.activeElement===button;let focusMoved=false;
 const focusElsewhere=e=>{if(e.target!==document.body&&!button.contains(e.target))focusMoved=true;};
 const pointerElsewhere=e=>{if(!button.contains(e.target))focusMoved=true;};
 const windowBlur=()=>{focusMoved=true;};
 document.addEventListener("focusin",focusElsewhere);document.addEventListener("pointerdown",pointerElsewhere);window.addEventListener("blur",windowBlur);
 invalidateRegisteredUI();let adopted=false,invalidated=false;prepareBusy=true;prepareProgress={ticket,sessionId:sid,started:performance.now()};error();controls();
 try{
  const prepared=await api("/api/chat/prepare",{session_id:sid,discovery_revision:revision,...requested,...(recovery?{recovery_id:recovery.id}:{})});
  if(!current())return;
  if(prepared?.id!==sid||!(recovery?(prepared.scout_recovery?.id===recovery.id&&prepared.scout_recovery.from_revision===revision&&prepared.scout?.disclosed&&prepared.scout.requested_revision===prepared.scout_recovery.target_revision):(prepared.discovery?.revision===revision||prepared.scout?.disclosed&&prepared.scout.requested_revision===revision)))throw new Error("대화 조건이 바뀌었습니다. 현재 조건을 확인한 뒤 다시 수소문해 주세요.");
  session=prepared;animateScoutKey=session.id+":"+session.scout.revision;adopted=true;autoScroll=false;
 }catch(e){if(current()){error(e.message);if(["scout_source_changed","scout_source_unsupported"].includes(e.code)&&e.session?.id===sid&&e.session.request_spec?.source_turn_id===before.request_spec?.source_turn_id&&(e.session.scout_recovery?.from_revision===before.request_spec?.revision||recovery&&e.session.request_spec?.source_revision===before.request_spec?.source_revision)){session=e.session;adopted=true;autoScroll=false;}else if(((e.code==="model_response_unavailable"||e.code==="model_response_budget_exhausted")&&e.retry_available===false)||e.code==="discovery_not_ready"||e.message==="현재 조건을 새 메시지로 확인한 뒤 수소문을 눌러 주세요."){session.discovery={...session.discovery,lookup_ready:false};if(session.scout_recovery)session.scout_recovery={...session.scout_recovery,available:false};invalidated=true;}}}
 finally{
  document.removeEventListener("focusin",focusElsewhere);document.removeEventListener("pointerdown",pointerElsewhere);window.removeEventListener("blur",windowBlur);
  if(prepareProgress?.ticket===ticket){resetPrepareProgress();if(ticket!==prepareTicket)controls();}
  if(ticket===prepareTicket){
   controls();
   if(adopted){render();}
   else if(current()){if(invalidated)render();else if(button.isConnected){button.disabled=!canPrepareDiscovery();button.textContent=scoutButtonLabel();}else render();}
   if(returnFocus&&(adopted||current())&&!focusMoved&&document.hasFocus()&&(document.activeElement===document.body||document.activeElement===button)){
    const target=adopted||invalidated||!button.isConnected?$("message"):button;
    if(!target.disabled)target.focus({preventScroll:true});
   }
  }
 }
}
function stopBusyCi(){
 ciBusyStarted=null;
 $("thread").querySelectorAll(".susomun-ci--busy").forEach(mark=>{mark.classList.remove("susomun-ci--busy");mark.style.removeProperty("--ci-busy-delay");});
}
function busyCiAttributes(){
 if(!busy||ciBusyStarted===null||controller?.signal.aborted)return 'class="susomun-ci"';
 // Each streamed render creates a new node; its negative delay preserves this attempt's phase.
 const elapsed=Math.max(0,performance.now()-ciBusyStarted)%2400;
 return 'class="susomun-ci susomun-ci--busy" style="--ci-busy-delay:-'+elapsed.toFixed(1)+'ms"';
}
const responseProgressLabels={preparing:"요청을 준비하고 있어요",submitting:"요청을 보내고 있어요",waiting:"응답을 기다리고 있어요",interpreting:"응답 처리 단계",searching:"자료 조회 단계",reading:"첨부 자료를 읽고 있어요",answering:"답변을 준비하고 있어요",receiving:"답변을 받고 있어요"};
function responseProgressLabel(){
 const label=busy&&!controller?.signal.aborted?responseProgressLabels[responseProgress]||"":"";
 return label&&retryDisplay?retryDisplay.name+"로 다시 시도 · "+label:label;
}
function syncResponseProgress(){
 // Keep one live node outside the replaced thread; announce only actual state changes.
 let live=$("responseProgressLive");
 if(!live){live=document.createElement("span");live.id="responseProgressLive";live.className="sr-only";live.setAttribute("role","status");live.setAttribute("aria-live","polite");live.setAttribute("aria-atomic","true");$("thread").before(live);}
 const label=responseProgressLabel();if(live.textContent!==label)live.textContent=label;
}
function render(){
 const messages=[...(session?.messages||[])];if(optimistic)messages.push(optimistic);
 const started=messages.length>0||profileUI?.isOpen();$("main").className=started?"welcome is-chat":"welcome";$("thread").hidden=!started;
 $("thread").innerHTML=messages.map(m=>m.role==="user"?'<article class="message user">'+esc(m.text)+(m.attachments?.length?'<div class="message-files">'+fileChips(m.attachments)+'</div>':"")+'</article>':'<article class="message assistant'+(m.status==="error"?' error-message':'')+'"><div class="message-meta"><span class="avatar"><span class="susomun-ci" aria-hidden="true"><span class="susomun-ci-h">H</span></span></span><span>'+esc(responseModelLabel(m))+'</span>'+(m.historical_assistant?'<span class="response-note">이전 조회</span>':'')+'</div><div class="message-body">'+formattedAnswer(m.text||"",m.role==="assistant"?m.status:null)+'</div>'+(m.status==="error"?'<p class="response-error">'+esc(displayError(m.error)||"응답이 중단됐어요. 다시 시도할 수 있습니다.")+'</p>'+(!canRetryMessage(m)?'':'<button class="retry" data-action="retry" data-id="'+esc(m.turn_id)+'">'+esc(retryButtonLabel(m))+'</button>'):m.status==="cancelled"?'<p class="response-note">응답을 중지했어요. 위 내용은 완성되지 않은 답변입니다.</p>':"")+(m.kind==="self_profile"?'<button type="button" class="text-button" data-action="profile-receipt" data-version="'+esc(m.profile_receipt?.version??"")+'">'+(m.profile_receipt?"변경 보기":"내 프로필 열기")+'</button>':"")+'</article>').join("");
 if(busy&&(responseProgress||streamText))$("thread").innerHTML+='<article class="message assistant" data-response-progress><div class="message-meta"><span class="avatar"><span '+busyCiAttributes()+' aria-hidden="true"><span class="susomun-ci-h">H</span></span></span><span aria-hidden="true" style="font-size:12px;line-height:1.6;letter-spacing:0;min-width:0">'+esc(responseProgressLabel())+'</span></div>'+(streamText?'<div class="message-body">'+formatted(streamText)+'</div>':"")+'</article>';
 syncResponseProgress();
 renderBrief();
 renderCandidates();controls();drawController?.refreshBoundary();scrollBottom();
}

const canPropose=c=>Boolean(c)&&c.proposal_allowed!==false&&!c.lookup_only;
function checkProposalSelection(ids){
 if(!Array.isArray(ids)||!ids.length)throw new Error("현재 근거로 제안할 인물을 선택해 주세요.");
 for(const id of ids){const c=session?.result?.candidates.find(x=>x.id===id);if(!canPropose(c))throw new Error(c?.proposal_unavailable_reason||"현재 시연 범위의 인물과 근거로 다시 찾아 주세요.");}
}
// Server-scoped registered-career results are browser-only, never proposal authority.
let registeredEpoch=0,registeredDetailTicket=0,registeredLetterTicket=0;
function registeredViewCurrent(s=session){
 const revision=s?.scout?.revision;
 if(accountNavigationPending||accountInvalidated||busy||prepareBusy||profileBusy||profileUI?.isOpen?.()||uploading||files.length||composerComposing||s?.pending||$("message").value.trim()||!s?.ready||!s.scout?.disclosed||s.scout.status!=="complete"||s.search_context?.kind==="stopped"||s.request_spec?.state!=="current"||!revision||revision!==s.discovery?.revision||revision!==s.prepared_discovery_revision||revision!==s.request_spec?.revision)return false;
 const source=s.request_spec.source_turn_id,latestUser=(s.messages||[]).filter(m=>m.role==="user").at(-1);
 return typeof s.id==="string"&&!!s.id&&typeof source==="string"&&!!source&&latestUser?.turn_id===source&&(s.messages||[]).some(m=>m.role==="assistant"&&m.status==="complete"&&m.turn_id===source);
}
function registeredEnvelope(s=session){
 if(!registeredViewCurrent(s))return null;
 const r=s.registered_experts,revision=s.scout.revision;
 if(!r||r.schema!=="registered_expert_lookup.v1"||r.audience!=="browser_only"||r.session_id!==s.id||r.revision!==revision||!r.source_turn_id||r.source_turn_id!==s.request_spec.source_turn_id||typeof r.snapshot_id!=="string"||!r.snapshot_id||typeof r.corpus_fingerprint!=="string"||!r.corpus_fingerprint||r.model_data_sent!==false||r.can_propose!==false||r.delivery_allowed!==false||!Number.isInteger(r.candidate_count)||!Array.isArray(r.candidates)||r.candidate_count!==r.candidates.length||r.candidates.length>7)return null;
 const ids=new Set();
 for(const c of r.candidates){
  if(!c||typeof c.id!=="string"||!c.id||ids.has(c.id)||typeof c.name!=="string"||!c.name||typeof c.reason!=="string"||typeof c.purpose_missing!=="string"||!Array.isArray(c.unverified_conditions)||!c.unverified_conditions.every(v=>typeof v==="string")||!Array.isArray(c.evidence)||!c.evidence.every(e=>e&&typeof e==="object"&&!Array.isArray(e))||c.purpose_relation!=="unknown"||c.proposal_allowed!==false||c.lookup_only!==false||c.individual_performance_verified!==false||c.availability!=="미확인"||typeof c.can_review_draft!=="boolean")return null;
  ids.add(c.id);
 }
 return r;
}
function registeredBinding(r=registeredEnvelope()){
 return r?JSON.stringify([r.session_id,r.revision,r.source_turn_id,r.snapshot_id,r.corpus_fingerprint]):null;
}
function currentRegisteredCandidate(id){return registeredEnvelope()?.candidates.find(c=>c.id===id)||null;}
function registeredContextHtml(c){
 const limits=[c.purpose_missing,...c.unverified_conditions].filter(v=>typeof v==="string"&&v.trim());
 return '<section class="candidate-request-context"><h3>이번 질문과의 연결</h3><p>'+esc(c.reason)+'</p><p class="candidate-purpose-label">등록 이력에서 찾은 후보 · 수행·가용성 미확인</p>'+
  (limits.length?'<h4>확인이 필요한 점</h4><ul>'+limits.map(v=>'<li>'+esc(v)+'</li>').join('')+'</ul>':'')+
  '<h4>연결된 등록 근거</h4>'+c.evidence.map(e=>'<section class="detail-record"><h3>'+esc(e.title||e.id||'등록 근거')+'</h3><p>'+esc([e.date,e.role,e.scope_label||e.scope].filter(Boolean).join(' · '))+'</p>'+(e.excerpt?'<p>'+esc(e.excerpt)+'</p>':'')+(e.boundary?'<p>'+esc(e.boundary)+'</p>':'')+(safeUrl(e.url)?'<a href="'+esc(e.url)+'" target="_blank" rel="noopener noreferrer">출처 보기 ↗</a>':'')+extraRecordSources(e)+'</section>').join('')+'</section>';
}
function registeredRequestAction(c){
 return '<section class="detail-record" aria-label="등록 전문가 의뢰 검토"><p><strong>'+esc(c.name)+'</strong>님과 논의할 의뢰</p>'+
  (c.can_review_draft?'<button type="button" class="primary" data-action="registered-letter" data-id="'+esc(c.id)+'">의뢰 초안 검토 ↗</button>':typeof c.proposal_unavailable_reason==="string"&&c.proposal_unavailable_reason.trim()?'<p class="small subtle">'+esc(c.proposal_unavailable_reason)+'</p>':'')+
  '<p class="small subtle">검토용 초안이에요. 연락 의향·수행 가능 여부는 미확인이며 저장하거나 발송하지 않습니다.</p></section>';
}
function invalidateRegisteredUI(){
 registeredEpoch++;registeredDetailTicket++;registeredLetterTicket++;
 $("registeredExpertsZone")?.remove();
 if($("detailDialog").dataset.registeredReview==="true"){$("detailDialog").close();delete $("detailDialog").dataset.registeredReview;$("detailContent").replaceChildren();}
 if(letter?.kind==="registered_review"){$("letterDialog").close();$("letterBody").value="";letter=null;$("draftButton").disabled=true;$("proposeButton").disabled=true;}
}
function renderRegisteredExperts(){
 const r=registeredEnvelope();let zone=$("registeredExpertsZone");
 const lookupError=registeredViewCurrent()&&typeof session.registered_experts_error==="string"?session.registered_experts_error.trim():"";
 if(lookupError){
  if(letter?.kind==="registered_review"||$("detailDialog").dataset.registeredReview==="true")invalidateRegisteredUI();
  zone=$("registeredExpertsZone");
  if(!zone){zone=document.createElement("section");zone.id="registeredExpertsZone";zone.className="proposal-zone";zone.setAttribute("aria-label","등록 이력 조회 안내");$("proposalZone").after(zone);}
  zone.dataset.renderKey="error:"+lookupError;
  zone.innerHTML='<section class="detail-record"><h3>등록 이력 조회 안내</h3><p class="response-error" role="alert">'+esc(lookupError)+'</p></section>';return;
 }
 if(!r||!r.candidates.length){zone?.remove();if(!r&&(letter?.kind==="registered_review"||$("detailDialog").dataset.registeredReview==="true"))invalidateRegisteredUI();return;}
 if((letter?.kind==="registered_review"&&letter.registeredBinding!==registeredBinding(r))||($("detailDialog").dataset.registeredReview==="true"&&$("detailDialog").dataset.registeredBinding!==registeredBinding(r)))invalidateRegisteredUI();
 zone=$("registeredExpertsZone");
 if(!zone){zone=document.createElement("section");zone.id="registeredExpertsZone";zone.className="proposal-zone";zone.setAttribute("aria-label","등록 이력 연결 후보");$("proposalZone").after(zone);}
 const key=JSON.stringify(r);if(zone.dataset.renderKey===key)return;zone.dataset.renderKey=key;
 zone.innerHTML='<div class="collection-heading"><div><h2>등록 이력에서 찾은 사람</h2><p class="small subtle">이번 질문과 연결되는 등록 경력·논문·특허 이력이에요. AI의 공개 논문 조회와 별도로 검색했으며 이 자료를 AI에 추가 전송하지 않았습니다.</p></div><span class="collection-count">'+r.candidate_count+'</span></div>'+
 r.candidates.map(c=>'<article class="detail-record"><h3>'+esc(c.name)+'</h3><p>'+esc([c.org,c.role].filter(Boolean).join(' · '))+'</p>'+registeredContextHtml(c)+'<button type="button" class="secondary" data-action="registered-person" data-id="'+esc(c.id)+'">인물 상세 보기 ↗</button>'+registeredRequestAction(c)+'</article>').join('');
}
async function openRegisteredLetter(id){
 const source=session,r=registeredEnvelope(),c=r?.candidates.find(row=>row.id===id),binding=registeredBinding(r),epoch=registeredEpoch,ticket=++registeredLetterTicket;
 if(!c?.can_review_draft)throw new Error("현재 등록 후보에서 의뢰 초안을 다시 열어 주세요.");
 const draft=await api("/api/registered-experts/draft",{session_id:source.id,candidate_id:id,snapshot_id:r.snapshot_id,revision:r.revision});
 if(ticket!==registeredLetterTicket||epoch!==registeredEpoch||session!==source||registeredBinding()!==binding||!currentRegisteredCandidate(id)?.can_review_draft)throw new Error("대화 조건이 바뀌어 이전 검토 초안을 열지 않았어요.");
 if(draft?.kind!=="registered_review"||draft.review_kind!=="registered_career"||draft.can_propose!==false||draft.proposal_allowed!==false||draft.delivery_allowed!==false||draft.model_data_sent!==false||draft.session_id!==source.id||draft.revision!==r.revision||draft.snapshot_id!==r.snapshot_id||draft.source_turn_id!==r.source_turn_id||draft.candidate?.id!==id||draft.candidate.name!==c.name||typeof draft.body!=="string"||!draft.body.trim()||draft.body.length>30000)throw new Error("검토 초안의 권한과 현재 후보를 확인하지 못했어요.");
 letter={kind:"registered_review",registeredBinding:binding,ids:[id],drafts:[draft],sessionId:source.id,index:0,candidateContexts:{[id]:JSON.parse(JSON.stringify(c))},bodies:{[id]:draft.body}};
 renderLetter();modal("letterDialog");
}

function extraRecordSources(e){
 return (Array.isArray(e.metadata_sources)?e.metadata_sources:[]).filter(x=>safeUrl(x.url)).map(x=>'<p><a href="'+esc(x.url)+'" target="_blank" rel="noopener noreferrer">'+esc(x.title||x.label||(/correction/i.test(x.basis||x.type||'')?'정정 출처':'추가 확인 출처'))+' ↗</a></p>').join('');
}

// Display only: relation and limitations belong to this saved result, not the profile.
function candidatePurposeRelation(candidate){
 return ['direct','adjacent'].includes(candidate?.purpose_relation)?candidate.purpose_relation:'';
}
function candidatePurposeLabel(candidate){
 const relation=candidatePurposeRelation(candidate);
 return relation==='adjacent'?'인접 분야 후보 · 직접 근거 부족':relation==='direct'?'직접 관련 후보':'';
}
function candidateRelationSummary(rows,result){
 const counts={direct:0,adjacent:0,unknown:0};
 for(const candidate of rows)counts[candidatePurposeRelation(candidate)||'unknown']++;
 const values=[result?.direct_candidate_count,result?.adjacent_candidate_count,result?.matched_candidate_count];
 if(counts.unknown||!rows.length||!values.every(v=>Number.isInteger(v)&&v>=0)||values[0]!==counts.direct||values[1]!==counts.adjacent||values[2]!==rows.length||values[0]+values[1]!==values[2])return '';
 return '직접 관련 '+counts.direct+'명 · 인접 분야 '+counts.adjacent+'명';
}
function candidateContextHtml(candidate){
 const relation=candidatePurposeRelation(candidate);if(!relation)return '';
 const missing=typeof candidate.purpose_missing==='string'?candidate.purpose_missing.trim():'';
 const reason=typeof candidate.reason==='string'?candidate.reason.trim():'';
 const evidence=(Array.isArray(candidate.evidence)?candidate.evidence:[]).filter(e=>e&&typeof e==='object');
 return '<section class="candidate-request-context" data-purpose-relation="'+relation+'"><h3>이번 요청과의 연결</h3><p class="candidate-purpose-label">'+candidatePurposeLabel(candidate)+'</p>'+
  (reason?'<p>'+esc(reason)+'</p>':'')+
  (missing?'<h4>추가 확인사항</h4><p>'+esc(missing)+'</p>':'')+
  (evidence.length?'<h4>이번 판단에 연결된 근거</h4><ul>'+evidence.map(e=>'<li><strong>'+esc(e.title||e.id||'연결 근거')+'</strong>'+(e.scope_label||e.scope?'<p>'+esc(e.scope_label||e.scope)+'</p>':'')+(e.excerpt?'<p>'+esc(e.excerpt)+'</p>':'')+(e.boundary?'<p>'+esc(e.boundary)+'</p>':'')+(safeUrl(e.url)?'<a href="'+esc(e.url)+'" target="_blank" rel="noopener noreferrer">원문 출처 ↗</a>':'')+extraRecordSources(e)+'</li>').join('')+'</ul>':'')+'</section>';
}
function captureCandidateContexts(source,ids){
 return Object.fromEntries(ids.map(id=>{
  const candidate=source?.result?.candidates?.find(c=>c.id===id);
  if(!candidatePurposeRelation(candidate))return [id,null];
  return [id,JSON.parse(JSON.stringify({purpose_relation:candidate.purpose_relation,purpose_missing:candidate.purpose_missing,reason:candidate.reason,evidence:candidate.evidence}))];
 }));
}
function renderLetterCandidateContext(id){
 let context=$('letterCandidateContext');
 const contextCandidate=letter?.candidateContexts?.[id];
 const html=letter?.kind==="registered_review"&&contextCandidate?registeredContextHtml(contextCandidate):candidateContextHtml(contextCandidate);
 if(!html){context?.remove();return;}
 if(!context){context=document.createElement('div');context.id='letterCandidateContext';$('letterDialog').querySelector('.dialog-heading').after(context);}
 context.innerHTML=html;
}

function cardCapability(c){
 const profile=c.profile||{},values=[profile.tagline,...(Array.isArray(profile.skills)?profile.skills:[]),...(Array.isArray(profile.topics)?profile.topics:[]).map(t=>t?.name)];
 // Select a complete registered field, never a clipped sentence or AI reason.
 // Twenty full-width glyphs fit the mobile card's 242px line at 12px.
 return values.filter(v=>typeof v==="string").map(v=>v.replace(/\s+/g," ").trim()).find(v=>v&&Array.from(v).length<=20)||"등록 이력과 근거 보기";
}
// Cards show the ~40 KB WebP derivative; the ~3 MB original PNGs missed the card's image deadline on phones.
function cardPortrait(path){return typeof path==="string"&&/^\/portraits\/[A-Za-z0-9_.-]+\.(png|jpe?g|webp)$/.test(path)?path.replace(/\.(?:png|jpe?g)$/i,'-detail.webp'):'';}
async function candidateDrawRecords(rows,gemini,historical,signal){
 return Promise.all(rows.map(async c=>{
  const record={id:c.id,name:c.profile?.display_name||c.name,portrait:cardPortrait(c.profile?.portrait?.path),capability:cardCapability(c),purpose_relation:candidatePurposeRelation(c),purpose_missing:typeof c.purpose_missing==='string'?c.purpose_missing:'',reason:typeof c.reason==='string'?c.reason:''};
  if(!gemini||historical||c.in_current_pool===false||typeof c.id!=="string"||!c.id)return record;
  try{
   const person=await api("/api/person?id="+encodeURIComponent(c.id),undefined,signal);
   if(signal?.aborted||person?.id!==c.id)return record;
   // Display data only: never write it into the session, candidates or model payload.
   const profile=person.profile||{},path=profile.portrait?.path;
   return {...record,name:typeof profile.display_name==="string"&&profile.display_name?profile.display_name:record.name,portrait:cardPortrait(path),capability:cardCapability({profile})};
  }catch{return record;}
 }));
}
function emptyCandidateNotice(s){
 const result=s?.result,scout=s?.scout;
 // Only abbreviate a completed zero-card assessment; keep other result notices intact.
 if(!s?.pending&&scout?.status==="complete"&&scout.count_status==="known"&&scout.count===0&&Array.isArray(result?.candidates)&&result.candidates.length===0&&result.assessment_status==="accepted"&&result.lookup_resolution==="no_purpose_supported_records"&&!result.inspection_only)return '현재 요청에 맞는 연결 후보를 확정하지 못했어요.';
 return result?.empty_message||'현재 자료에서 요청을 뒷받침하는 인물을 찾지 못했어요.';
}
function renderCandidates(){
 const zone=$("proposalZone");
 const disclosed=session?.scout?.disclosed===true&&session.scout.revision===session.discovery?.revision;
 zone.hidden=!session?.ready||busy||!disclosed;
 if(zone.hidden){drawEpoch++;drawMetadataController?.abort();drawMetadataController=null;drawController?.dispose();drawController=null;drawRenderKey="";zone.replaceChildren();return;}
 if(accountNavigationPending||accountInvalidated)return;
 const result=session.result||{},rows=result.candidates||[],key=session.id+":"+session.scout.revision;
 const mapEligible=!result.historical_result&&!result.inspection_only&&rows.every(c=>c.in_current_pool!==false);
 const paperScope=hasPublicPaperScope(session);
 const emptyNotice=rows.length?"":(paperScope?'공개 논문 조회: ':'')+emptyCandidateNotice(session),relationSummary=candidateRelationSummary(rows,result);
 const renderKey=key+":"+JSON.stringify(rows)+":"+mapEligible+":"+JSON.stringify(relationSummary)+(rows.length?"":":"+JSON.stringify(emptyNotice));
 if(renderKey===drawRenderKey)return;
 drawMetadataController?.abort();
 drawRenderKey=renderKey;const epoch=++drawEpoch;
 drawController?.dispose();drawController=null;
 const animate=animateScoutKey===key;animateScoutKey="";
 zone.classList.add("scout-draw-zone");
 zone.innerHTML='<div class="collection-heading"><div><h2>'+(paperScope?'공개 논문에서 찾은 사람':'현재 요청과 연결된 사람')+'</h2>'+(rows.length?'<p id="scoutResultHint">연결된 사람을 불러오고 있어요.</p>':'')+(relationSummary?'<p class="candidate-relation-summary">'+esc(relationSummary)+'</p>':'')+'</div><span class="collection-count">'+rows.length+'</span></div><div id="scoutDrawHost"></div>';
 if(!rows.length){$("scoutDrawHost").textContent=emptyNotice;if(animate)zone.scrollIntoView({block:"start",behavior:"instant"});return;}
 const metadataController=new AbortController();drawMetadataController=metadataController;
 // Fixed diagnostics only: never log candidates, session IDs, responses or raw errors.
 let mapFallbackReason=result.historical_result?'historical_result':result.inspection_only?'inspection_only':!mapEligible?'outside_current_pool':'map_unavailable';
 let mapFallbackPart='';
 let settleMapTimeout;
 const metadataTimeout=setTimeout(()=>{if(mapEligible)mapFallbackReason='map_timeout';metadataController.abort();settleMapTimeout?.(null);},15000);
 // The full map is display-only. Recommendation IDs and evidence remain the saved result.
 const mapRequest=mapEligible?Promise.race([Promise.all([api("/api/people-map",undefined,metadataController.signal),import('/recommendation-map.js')]).catch(()=>{if(mapFallbackReason!=='map_timeout')mapFallbackReason='map_load_failed';return null;}),new Promise(resolve=>{settleMapTimeout=resolve;})]):Promise.resolve(null);
 Promise.all([candidateDrawRecords(rows,hasPublicPaperScope(session),Boolean(result.historical_result),metadataController.signal),import('/draw.js'),mapRequest]).then(([records,{initDraw},map])=>{
  if(epoch!==drawEpoch||drawRenderKey!==renderKey||zone.hidden||accountNavigationPending||accountInvalidated)return;
  const host=$("scoutDrawHost"),hint=$("scoutResultHint"),dock=document.querySelector(".composer-dock");
  const options={bottomBoundary:dock,onBoundaryFit:fits=>dock?.classList.toggle("scout-dock-in-flow",!fits),quiet:()=>!animate||RndCraft.quiet(),onDetail:record=>openPersonCard(record.id,document.activeElement).catch(exc=>error(exc.message))};
  if(map){
   try{
    const [mapData,{initRecommendationMap}]=map;
    drawController=initRecommendationMap(host,{...options,quiet:()=>RndCraft.quiet(),animateOnShow:animate,mapData,rows,records});
    drawController.show(records,key);
    hint.textContent='관련 분야를 따라 연결된 사람을 살펴보세요. 이번 요청의 후보와 근거 범위는 아래 목록에서 확인할 수 있어요.';
   }catch(error){
    mapFallbackReason=error?.code==='recommendation_map_layout_not_ready'?'layout_not_ready':'initialization_failed';
    const layoutParts=['mount','stage','layer-structure','layer-style','node','person-size','face-structure','face-style','face-image'];
    if(mapFallbackReason==='layout_not_ready'&&layoutParts.includes(error.layoutPart))mapFallbackPart=error.layoutPart;
    drawController?.dispose();drawController=null;host.replaceChildren();options.onBoundaryFit(true);
   }
  }
  if(!drawController){
   drawController=initDraw(host,options);drawController.show(records,key);
   try{console.warn('recommendation-map-fallback',{reason:mapFallbackReason,...(mapFallbackPart?{layoutPart:mapFallbackPart}:{})});}catch{}
   hint.textContent=mapEligible?'연구맵을 불러오지 못해 후보 카드를 보여드려요. 카드를 누르면 근거를 볼 수 있어요.':'카드를 누르면 이 결과에 연결된 이력과 근거를 볼 수 있어요.';
  }
  if(animate)zone.scrollIntoView({block:"start",behavior:"instant"});
 }).catch(()=>{if(epoch===drawEpoch&&!accountNavigationPending&&!accountInvalidated){drawRenderKey="";$("scoutDrawHost").textContent='인물 카드를 불러오지 못했어요. 화면을 새로고침해 주세요.';}}).finally(()=>{metadataController.abort();clearTimeout(metadataTimeout);if(drawMetadataController===metadataController)drawMetadataController=null;});
}
new MutationObserver(()=>drawController?.setQuiet()).observe(document.body,{attributes:true,attributeFilter:['class']});
// Status recovery reads the same saved turn; it never submits a model request.
const RECOVERY_GET_TIMEOUT_MS=8000,RECOVERY_WINDOW_MS=24000,RECOVERY_INTERVAL_MS=1500;
let recoveryEpoch=0,recoveryState=null;
const recoveryReports=new Set();
function recoveryTurn(saved){return Array.isArray(saved?.messages)?saved.messages.filter(m=>m.role==="user").at(-1)?.turn_id:null;}
function recoveryCurrent(state,ticket=state?.epoch){return !!state&&recoveryState===state&&ticket===recoveryEpoch&&!accountNavigationPending&&!accountInvalidated&&session?.id===state.sessionId&&recoveryTurn(session)===state.turnId;}
function clearRecoveryNotice(state){if(state?.notice&&$("composerError").textContent===state.notice)error();}
function invalidateRecovery(clearNotice=false){
 cancelAttachmentClientReports();
 const old=recoveryState;recoveryEpoch++;recoveryState=null;old?.controller?.abort();
 for(const c of recoveryReports)c.abort();recoveryReports.clear();
 if(clearNotice)clearRecoveryNotice(old);renderRecoveryControl();return old;
}
function renderRecoveryControl(){
 let button=$("recoveryCheckButton");
 if(!button){button=document.createElement("button");button.id="recoveryCheckButton";button.type="button";button.className="text-button";button.dataset.action="recovery-status";$("composerError").after(button);}
 const state=recoveryState;button.hidden=!recoveryCurrent(state)||!['pending','unavailable'].includes(state.outcome);
 button.disabled=!!state?.active||composerClientLocked();button.textContent=state?.active?"응답 상태를 확인하고 있어요…":"응답 상태 다시 확인";
}
function recoveryNotice(state,outcome){
 if(!recoveryCurrent(state))return;
 state.outcome=outcome;state.notice=outcome==="pending"?"저장된 응답이 아직 처리 중이에요. 상태를 다시 확인하거나 이전 대화에서 열어 주세요.":"저장된 응답 상태를 확인하지 못했어요. 상태를 다시 확인해 주세요. 질문은 다시 전송하지 않습니다.";
 error(state.notice);renderRecoveryControl();
}
function reportRecovery(state,outcome,errorKind,httpStatus){
 if(!recoveryCurrent(state)||!token||!/^[-A-Za-z0-9]{16,80}$/.test(state.sessionId)||!/^[-A-Za-z0-9]{16,80}$/.test(state.turnId))return;
 const data={session_id:state.sessionId,turn_id:state.turnId,outcome,elapsed_ms:Math.min(3600000,Math.max(0,Math.round(performance.now()-state.started))),poll_count:Math.min(100,state.pollCount)};
 if(/^[a-f0-9]{32}$/.test(state.requestId||""))data.request_id=state.requestId;
 if(['eof','aborted','stream_error','http','network','timeout','invalid_response'].includes(errorKind))data.error_kind=errorKind;
 if(Number.isInteger(httpStatus)&&httpStatus>=100&&httpStatus<=599)data.http_status=httpStatus;
 const body=JSON.stringify(data);if(new TextEncoder().encode(body).length>2048)return;
 const c=new AbortController();recoveryReports.add(c);const timer=setTimeout(()=>c.abort(),2000);
 // Diagnostics are silent and best effort; their response cannot change the conversation.
 Promise.resolve().then(()=>{if(!recoveryCurrent(state))return;return fetch('/api/chat/recovery-report',{method:'POST',headers:{'Content-Type':'application/json','X-RnDplz-Token':token},body,signal:c.signal});}).catch(()=>{}).finally(()=>{clearTimeout(timer);recoveryReports.delete(c);});
}
function recoveryReadError(kind,status){const e=new Error(kind);e.recoveryKind=kind;if(status)e.httpStatus=status;return e;}
async function readRecoverySession(state,ticket,remaining){
 const c=new AbortController();state.controller=c;let timedOut=false,timer,onAbort;
 const cancelled=new Promise((_,reject)=>{onAbort=()=>reject(recoveryReadError(timedOut?'timeout':'aborted'));c.signal.addEventListener('abort',onAbort,{once:true});timer=setTimeout(()=>{timedOut=true;c.abort();},Math.min(RECOVERY_GET_TIMEOUT_MS,remaining));});
 const read=async()=>{
  let response;try{response=await fetch('/api/chat/session?id='+encodeURIComponent(state.sessionId),{signal:c.signal,cache:'no-store'});}catch(e){if(c.signal.aborted)throw recoveryReadError(timedOut?'timeout':'aborted');throw recoveryReadError('network');}
  if(!response.ok)throw recoveryReadError('http',response.status);
  let saved;try{saved=await response.json();}catch(e){if(c.signal.aborted)throw recoveryReadError(timedOut?'timeout':'aborted');throw recoveryReadError('invalid_response',response.status);}
  if(!recoveryCurrent(state,ticket))throw recoveryReadError('aborted');
  if(saved?.id!==state.sessionId||recoveryTurn(saved)!==state.turnId||!(saved.pending===null||saved.pending===state.turnId))throw recoveryReadError('invalid_response',response.status);
  return saved;
 };
 try{return await Promise.race([read(),cancelled]);}finally{clearTimeout(timer);c.signal.removeEventListener('abort',onAbort);if(state.controller===c)state.controller=null;}
}
async function recoverSavedTurn(state){
 if(!recoveryCurrent(state)||state.active)return;
 const ticket=state.epoch,deadline=performance.now()+RECOVERY_WINDOW_MS;state.active=true;state.pollCount=0;let last={kind:'unavailable',error:'timeout'};renderRecoveryControl();
 try{
  while(recoveryCurrent(state,ticket)&&performance.now()<deadline&&state.pollCount<100){
   state.pollCount++;
   try{
    const saved=await readRecoverySession(state,ticket,deadline-performance.now());if(!recoveryCurrent(state,ticket))return;
    if(saved.pending===null){
     session=saved;updateHistory();clearRecoveryNotice(state);state.outcome='recovered';reportRecovery(state,'recovered');
     state.active=false;render();return;
    }
    last={kind:'pending'};
   }catch(e){
    if(!recoveryCurrent(state,ticket))return;
    last={kind:'unavailable',error:e.recoveryKind||'network',status:e.httpStatus};
    if(e.recoveryKind==='http'&&[400,401,403,404].includes(e.httpStatus))break;
   }
   const remaining=deadline-performance.now();if(remaining<=0)break;
   await new Promise(resolve=>setTimeout(resolve,Math.min(RECOVERY_INTERVAL_MS,remaining)));
  }
  if(!recoveryCurrent(state,ticket))return;
  recoveryNotice(state,last.kind);reportRecovery(state,last.kind,last.error,last.status);
 }finally{if(recoveryCurrent(state,ticket)){state.active=false;renderRecoveryControl();}}
}
async function beginStreamRecovery(payload,requestId,kind){
 invalidateRecovery();
 if(!session?.id||recoveryTurn(session)!==payload.turn_id)return;
 const state={epoch:recoveryEpoch,sessionId:session.id,turnId:payload.turn_id,requestId,started:performance.now(),pollCount:0,active:false,notice:$("composerError").textContent,outcome:null,controller:null};
 recoveryState=state;reportRecovery(state,'stream_interrupted',kind);await recoverSavedTurn(state);
}
function restoreRecoveryAfterHistory(prior,saved){
 clearRecoveryNotice(prior);
 if(!prior||saved.id!==prior.sessionId||recoveryTurn(saved)!==prior.turnId)return;
 const state={...prior,epoch:recoveryEpoch,active:false,controller:null,notice:null,pollCount:0};recoveryState=state;
 if(saved.pending===null){state.outcome='recovered';reportRecovery(state,'recovered');}
 else if(saved.pending===state.turnId)recoveryNotice(state,'pending');
 renderRecoveryControl();
}

function restoreRecoveryAfterHistoryFailure(prior,previousSession,navigationEpoch){
 if(!prior||navigationEpoch!==recoveryEpoch||accountNavigationPending||accountInvalidated||session!==previousSession||session?.id!==prior.sessionId||recoveryTurn(session)!==prior.turnId)return;
 recoveryState={...prior,epoch:recoveryEpoch,active:false,controller:null};renderRecoveryControl();
}

function updateHistory(){if(!session)return;const row={id:session.id,title:session.original.slice(0,60),updated:session.updated,model_id:session.model_id,model_selection_origin:selectionOrigin(session.model_selection_origin),...(hasPublicPaperScope(session)?{provider_scope:{...session.provider_scope}}:{})};history=[row,...history.filter(s=>s.id!==row.id)];}
async function retryTurn(id){
 const user=session?.messages.find(m=>m.turn_id===id&&m.role==="user"),assistant=session?.messages.find(m=>m.turn_id===id&&m.role==="assistant");
 if(!user)throw new Error("다시 시도할 원래 요청을 확인하지 못했어요. 대화를 다시 열어 주세요.");
 if(!canRetryMessage(assistant))return;
 await send({text:user.input_text??user.text,session_id:session.id,attachments:(user.attachments||[]).map(f=>f.id),...selectedRequestModel(),turn_id:id,...(user.person_id?{person_id:user.person_id}:{})});
}
async function send(payload,submission=null){
 if(composerSendLocked()){restoreComposerDraft(submission);return;}
 if(!catalog.some(m=>m.id===payload.model_id&&m.enabled)){restoreComposerDraft(submission);error("선택한 모델을 지금 사용할 수 없어요. 사용 가능한 모델을 선택해 주세요.");return;}
 const boundary=modelBoundaryMessage(payload.model_id,payload.attachments||[],session,payload.turn_id);if(boundary){restoreComposerDraft(submission);error(boundary);return;}
 if(isPublicPaperModel(payload.model_id)&&((payload.person_id&&!isPublicPaperSession())||(payload.model_selection_origin!=="explicit"&&!(payload.model_selection_origin==="automatic"&&(isPublicPaperSession()||(!session?.id&&modelDefault===payload.model_id)))))){restoreComposerDraft(submission);error("외부 모델은 새 대화에서 공개 논문을 조회해 주세요.");return;}
 const repeated=!!session?.messages.some(m=>m.turn_id===payload.turn_id&&m.role==="user"),epoch=modelSelectionEpoch;
 payload={...payload,model_selection_origin:selectionOrigin(payload.model_selection_origin)};
 const briefSubmission=beginBriefSubmission(payload),briefSubmissionSession=payload.session_id;
 invalidateRegisteredUI();invalidateRecovery(true);prepareTicket++;error();streamText="";busy=true;responseProgress="preparing";ciBusyStarted=performance.now();autoScroll=true;controller=new AbortController();controller.signal.addEventListener("abort",()=>{stopBusyCi();responseProgress="";render();},{once:true});retryPayload=payload;retryDisplay=repeated?{turn_id:payload.turn_id,model_id:payload.model_id,name:catalog.find(m=>m.id===payload.model_id)?.name||payload.model_id}:null;
 if(!session?.messages.some(m=>m.turn_id===payload.turn_id&&m.role==="user"))optimistic={role:"user",text:payload.text||"첨부한 자료를 함께 검토해 주세요.",attachments:files};
 render();let accepted=false,finished=false,recoveryRequestId=null;
 try{
  // Only a new request with a known automatic guide choice checks recovery.
  // Retry preserves the original request and uses the current model selection; no input is auto-resubmitted.
  if(!payload.session_id&&!repeated&&payload.model_id==="guide"&&payload.model_selection_origin==="automatic"){
   if(!await refreshModelOptions("/api/chat/models"))throw new Error("모델 목록이 갱신 중입니다. 선택 상태를 확인한 뒤 보내 주세요.");
   const next=resolveModelSelection(catalog,modelDefault,payload.model_id,payload.model_selection_origin);
   payload={...payload,model_id:next.id,model_selection_origin:next.origin};retryPayload=payload;
   if(epoch===modelSelectionEpoch){selectedModel=next.id;modelSelectionOrigin=next.origin;renderModelSelect();}
  }
  if(controller.signal.aborted){const stopped=new Error("응답을 중지했어요.");stopped.name="AbortError";throw stopped;}
  responseProgress="submitting";render();
  const response=await fetch("/api/chat",{method:"POST",headers:{"Content-Type":"application/json","X-RnDplz-Token":token},body:JSON.stringify(payload),signal:controller.signal});
  const rid=response.headers?.get("X-Rndplz-Request-Id");if(/^[a-f0-9]{32}$/.test(rid||""))recoveryRequestId=rid;
  if(!response.ok){const data=await response.json();throw new Error(data.error||"대화를 시작하지 못했어요.");}
  const reader=response.body.getReader(),decoder=new TextDecoder();let buffer="";
  const event=line=>{if(!line.trim())return;const data=JSON.parse(line);
   if(data.type==="start"){if(!finished)responseProgress="waiting";session=data.session;if(/^[a-f0-9]{32}$/.test(data.request_id||""))recoveryRequestId=data.request_id;accepted=true;updateHistory();optimistic=null;if(submission){files=files.filter(f=>!submission.attachmentIds.includes(f.id));for(const id of submission.attachmentIds)inlineMessageLinks.delete(id);}renderFiles();window.history.replaceState(null,"","/?chat="+session.id);}
   if(!finished&&data.type==="phase")responseProgress=["interpreting","searching","reading","answering","waiting"].includes(data.phase)?data.phase:"waiting";
   if(data.type==="delta"){streamText+=data.text;if(!finished&&data.text)responseProgress="receiving";}
   if(data.type==="done"||data.type==="error"){session=data.session;finished=true;responseProgress="";stopBusyCi();streamText="";optimistic=null;updateHistory();if(data.type==="error")error(data.error);}
   render();
  };
  while(true){const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});let end;while((end=buffer.indexOf("\n"))>=0){event(buffer.slice(0,end));buffer=buffer.slice(end+1);}}
  buffer+=decoder.decode();if(buffer.trim())event(buffer);
  if(!finished){const failure=new Error("응답 연결이 끝났어요. 저장된 대화를 확인하고 다시 시도해 주세요.");failure.recoveryKind="eof";throw failure;}
 }catch(e){
  stopBusyCi();responseProgress="";render();
  if(finished){if(e.name!=="AbortError")error(e.message);return;}
  if(!accepted)restoreComposerDraft(submission);
  failBriefSubmission(briefSubmission,briefSubmissionSession);
  if(e.name==="AbortError"){error("응답 수신을 중지했어요.");}
  else error(e.message);
  if(accepted&&session)await beginStreamRecovery(payload,recoveryRequestId,e.recoveryKind==="eof"?"eof":e.name==="AbortError"?"aborted":"stream_error");
 }finally{stopBusyCi();busy=false;responseProgress="";retryDisplay=null;optimistic=null;streamText="";controller=null;resizeInput();render();if(!session?.pending)$("message").focus();}
}
function newChat(){if(composerClientLocked())return;invalidateRegisteredUI();invalidateRecovery(true);attachmentPreviewTicket++;prepareTicket++;profileUI.close();session=null;modelSelectionEpoch++;if(modelSelectionOrigin!=="explicit"){selectedModel="";modelSelectionOrigin="automatic";syncModelSelection();renderModelSelect();}files=[];inlineMessageLinks.clear();optimistic=null;retryPayload=null;$("message").value="";window.history.replaceState(null,"","/");error();autoScroll=true;renderFiles();render();resizeInput();$("message").focus();}
function dataUrl(file,signal){return new Promise((resolve,reject)=>{
 const reader=new FileReader(),finish=(fn,value)=>{signal?.removeEventListener("abort",stop);fn(value);};
 const stop=()=>{if(reader.readyState===1)reader.abort();finish(reject,attachmentAbortError());};
 reader.onload=()=>signal?.aborted?finish(reject,attachmentAbortError()):finish(resolve,String(reader.result).split(",")[1]);
 reader.onerror=()=>finish(reject,new Error("파일을 읽지 못했어요."));reader.onabort=()=>finish(reject,attachmentAbortError());
 signal?.addEventListener("abort",stop,{once:true});if(signal?.aborted){stop();return;}reader.readAsDataURL(file);
});}
// Pre-upload metadata is a client observation, never file content or model dispatch.
const ATTACHMENT_REPORT_EXTENSIONS=new Set(["txt","md","csv","json","log","pdf","docx","pptx","html","htm","png","jpg","jpeg","webp"]);
const ATTACHMENT_REPORT_MIMES=new Set(["text/plain","text/markdown","text/csv","application/json","application/pdf","application/vnd.openxmlformats-officedocument.wordprocessingml.document","application/vnd.openxmlformats-officedocument.presentationml.presentation","text/html","image/png","image/jpeg","image/webp"]);
const ATTACHMENT_REPORT_REASONS=new Set(["image_path_unsupported","scope_attachment_restricted","unsupported_file_type","batch_limit","name_invalid","empty_file","file_too_large"]);
let attachmentReportEpoch=0;
const attachmentClientReports=new Set();
function cancelAttachmentClientReports(){attachmentReportEpoch++;for(const c of attachmentClientReports)c.abort();attachmentClientReports.clear();}
function attachmentReportType(file){
 const suffix=typeof file?.name==="string"?file.name.match(/\.([^.]+)$/)?.[1]?.toLowerCase():null;
 const extension=!suffix?"none":ATTACHMENT_REPORT_EXTENSIONS.has(suffix)?suffix:"other";
 const suppliedMime=typeof file?.type==="string"?file.type.trim().toLowerCase():"";
 const mime=!suppliedMime?"none":ATTACHMENT_REPORT_MIMES.has(suppliedMime)?suppliedMime:"other";
 const category=["png","jpg","jpeg","webp"].includes(extension)||suppliedMime.startsWith("image/")?"image":
  (["txt","md","csv","json","log","pdf","docx","pptx","html","htm"].includes(extension)||["text/plain","text/markdown","text/csv","application/json","application/pdf","application/vnd.openxmlformats-officedocument.wordprocessingml.document","application/vnd.openxmlformats-officedocument.presentationml.presentation","text/html"].includes(mime))?"document":"other";
 return {extension,mime,category};
}
function attachmentReportModel(){
 if(!selectedModel)return "none";
 const chosen=catalog.find(m=>m.id===selectedModel);if(!chosen)return "other";
 if(chosen.id==="runtime")return "runtime";
 return ["guide","gemini","openai","claude","bridge","ollama"].includes(chosen.provider)?chosen.provider:"other";
}
function attachmentRejectionMessage(reason){
 const detail={
  image_path_unsupported:allowsScopedDocuments()?"이 대화에서는 이미지 첨부를 지원하지 않아요. 텍스트가 들어 있는 PDF·DOCX 등 지원 문서를 선택해 주세요.":"이 대화에서는 이미지와 문서를 첨부할 수 없어요. 문서는 새 대화에서 선택해 주세요.",
  scope_attachment_restricted:"이 대화에는 문서를 추가할 수 없어요. 새 대화에서 문서를 선택해 주세요.",
  unsupported_file_type:"지원하지 않는 파일 형식이에요. 문서는 TXT, MD, CSV, JSON, LOG, PDF, DOCX, PPTX, HTML, HTM을 지원해요."+(allowsScopedImages()?" 이미지는 PNG·JPEG·WebP를 지원해요.":"")
 }[reason];
 return "이번 선택은 추가하지 않았어요. "+detail+" 기존 첨부와 글은 유지돼요.";
}
function attachmentBatchDiagnostic(list){
 if(files.length+list.length>4)return {index:0,reason:"batch_limit"};
 for(let index=0;index<list.length;index++){
  const file=list[index];let reason="";
  if(!file.name||file.name.length>240)reason="name_invalid";
  else if(!/\.(txt|md|csv|json|log|pdf|docx|pptx|html?|htm|png|jpe?g|webp)$/i.test(file.name))reason="unsupported_file_type";
  else if(!Number.isSafeInteger(file.size)||file.size<=0)reason="empty_file";
  else if(file.size>ATTACHMENT_MAX_BYTES)reason="file_too_large";
  if(reason)return {index,reason};
 }
 return null;
}
function reportAttachmentRejection(list,index,reason){
 try{
 if(!token||accountNavigationPending||accountInvalidated||!ATTACHMENT_REPORT_REASONS.has(reason)||!Number.isInteger(index)||index<0||index>=list.length||list.length>10000)return;
 const file=list[index],kind=attachmentReportType(file),categories=new Set(list.map(attachmentReportType).map(x=>x.category));
 const data={client_event_id:crypto.randomUUID(),reason,category:categories.size>1?"mixed":kind.category,
  extension:kind.extension,mime:kind.mime,size_bytes:Number.isSafeInteger(file?.size)&&file.size>=0?file.size:0,
  batch_index:index+1,batch_count:list.length,selected_model:attachmentReportModel()};
 const body=JSON.stringify(data);if(new TextEncoder().encode(body).length>2048)return;
 const epoch=attachmentReportEpoch,selection=modelSelectionEpoch,currentSession=session,csrf=token;
 const c=new AbortController();attachmentClientReports.add(c);const timer=setTimeout(()=>c.abort(),2000);
 Promise.resolve().then(()=>{
  if(c.signal.aborted||epoch!==attachmentReportEpoch||selection!==modelSelectionEpoch||session!==currentSession||token!==csrf||accountNavigationPending||accountInvalidated)return;
  return fetch("/api/attachments/client-report",{method:"POST",headers:{"Content-Type":"application/json","X-RnDplz-Token":csrf},body,signal:c.signal});
 }).catch(()=>{}).finally(()=>{clearTimeout(timer);attachmentClientReports.delete(c);});
 }catch{} // Best-effort diagnostics must never replace the original attachment error.
}

async function upload(list){
 try{
  if(composerSendLocked())return;
  cancelAttachmentClientReports();
  const rejectedIndex=isPublicPaperContext()?list.findIndex(file=>!explicitScopedAttachment({file},selectedModel,session)):-1;
  if(rejectedIndex>=0){const reason=explicitImageAttachment({file:list[rejectedIndex]})?"image_path_unsupported":!allowsScopedDocuments()?"scope_attachment_restricted":"unsupported_file_type";error(attachmentRejectionMessage(reason));reportAttachmentRejection(list,rejectedIndex,reason);return;}
  const issue=attachmentBatchIssue(list);if(issue){error(issue);const rejected=attachmentBatchDiagnostic(list);if(rejected)reportAttachmentRejection(list,rejected.index,rejected.reason);return;}
  error();files.push(...list.map(file=>({id:"pending-"+crypto.randomUUID(),name:file.name,file})));
 }finally{$("fileInput").value="";renderFiles();}
}
async function submitComposer(){
 if(composerSendLocked()||composerComposing)return;
 const text=$("message").value.trim();if(!text&&!files.length)return;
 let attachmentPlan;try{attachmentPlan=planInlineMessageAttachments(text,files,inlineMessageLinks,()=>"pending-"+crypto.randomUUID());}catch(e){error(e.message);return;}
 const boundary=modelBoundaryMessage(selectedModel,attachmentPlan.files);if(boundary){error(boundary);return;}
 if(isPublicPaperContext()&&profileUI.shouldHandle(text)){error("내 프로필 작업은 이 외부 모델로 전송하지 않습니다. 새 대화에서 다른 모델을 선택하거나 내 프로필 페이지를 이용해 주세요.");return;}
 if(profileUI.shouldHandle(text)){
  if(attachmentPlan.urls.length||attachmentPlan.files.some(f=>f.source_url||f.source?.kind==="https_document")){error("링크 자료는 프로필로 전송하지 않습니다. 링크를 제거하고 프로필용 파일을 직접 선택해 주세요.");return;}
  if(attachmentPlan.files.some(f=>!f.file)){error("앞서 일반 대화용으로 전송한 파일은 제거하고 프로필용 파일을 다시 선택해 주세요.");return;}
  files=attachmentPlan.files;inlineMessageLinks=attachmentPlan.autoLinks;renderFiles();
  profileSubmission={text:$("message").value,revision:composerInputRevision,ids:files.map(f=>f.id)};
  try{await profileUI.submit(text,files.map(f=>f.file));}catch(e){error(e.message);}finally{if(!profileUI.hasPendingRequest())profileSubmission=null;render();resizeInput();}
  return;
 }
 let requested;try{requested=selectedRequestModel();}catch(e){error(e.message);return;}
 files=attachmentPlan.files;inlineMessageLinks=attachmentPlan.autoLinks;renderFiles();
 if(!text&&!files.length)return;
 const submittedFiles=[...files],submission=consumeComposerDraft();
 const payload={text,session_id:session?.id,attachments:[],...requested,turn_id:crypto.randomUUID()};
 const transfer={controller:null,cancelled:false};attachmentTransfer=transfer;uploading=true;resizeInput();let failed=false;
 try{
  for(let i=0;i<submittedFiles.length;i++){const f=submittedFiles[i];if(pendingAttachment(f)){const uploaded=await transmitAttachment(f,transfer,i+1,submittedFiles.length);requireAttachmentTransfer(transfer);acceptInlineAttachment(f,uploaded);submittedFiles[i]=uploaded;files=files.map(item=>item.id===f.id?uploaded:item);renderFiles();}}
  requireAttachmentTransfer(transfer);
 }catch(e){restoreComposerDraft(submission);error(e.message);failed=true;}
 finally{transfer.controller?.abort();if(attachmentTransfer===transfer)attachmentTransfer=null;uploading=false;attachmentStatus="";controls();}
 if(failed){resizeInput();if(!accountNavigationPending&&!accountInvalidated)$("message").focus();return;}
 submission.attachmentIds=submittedFiles.map(f=>f.id);
 await send({...payload,attachments:[...submission.attachmentIds]},submission);
}
function safeUrl(url){try{return ["https:","http:"].includes(new URL(url).protocol);}catch{return false;}}
// Presentation only: callers pass the current disclosed candidate, never a directory profile.
function detailRequestAction(candidate){
 if(!candidate)return '';
 const allowed=canPropose(candidate),reason=typeof candidate.proposal_unavailable_reason==='string'&&candidate.proposal_unavailable_reason.trim()?candidate.proposal_unavailable_reason:'현재 요청의 근거와 제안 가능 여부를 먼저 확인해 주세요.';
 const name=candidate.profile?.display_name||candidate.name||'선택한 인물';
 return '<section class="detail-record" aria-label="나의 의뢰"><p><strong>'+esc(name)+'</strong>님에게</p>'+
  (allowed?'<button type="button" class="primary" data-action="letter" data-id="'+esc(candidate.id)+'">나의 의뢰 보내기 ↗</button><p class="small subtle">'+(mailDelivery?'먼저 의뢰 초안을 확인해요. 보내기를 누르면 등록된 메일 주소로 발송하고 제안함에도 기록합니다.':'먼저 의뢰 초안을 확인해요. 실제 발송 없이 시연 제안함에만 기록합니다.')+'</p>':'<p><strong>지금은 의뢰를 보낼 수 없어요.</strong></p><p class="small subtle">'+esc(reason)+'</p>')+'</section>';
}
function currentDetailCandidate(id){
 const scout=session?.scout;
 if(!session?.ready||!scout?.disclosed||session.pending||!scout.revision||scout.revision!==session.discovery?.revision||scout.revision!==session.prepared_discovery_revision)return null;
 return session.result?.candidates?.find(candidate=>candidate.id===id)||null;
}
async function showPerson(id,opener=document.activeElement,registered=false){
 const registeredSource=session,registeredKey=registered?registeredBinding():null,registeredRequestEpoch=registeredEpoch,detailTicket=++registeredDetailTicket;
 if(registered&&!currentRegisteredCandidate(id))throw new Error("현재 등록 후보를 다시 확인해 주세요.");
 const stored=session?.result?.candidates.find(c=>c.id===id);
 const historical=Boolean(stored&&session?.result?.historical_result);
 const p=historical?stored:await api("/api/person?id="+encodeURIComponent(id));
 if(registered&&(detailTicket!==registeredDetailTicket||registeredRequestEpoch!==registeredEpoch||session!==registeredSource||registeredBinding()!==registeredKey||!currentRegisteredCandidate(id)))return;
 if(registered&&p?.id!==id)throw new Error("등록 인물 정보를 확인하지 못했어요.");
 const profile=RndCraft.profileDetails(p),candidate=registered?currentRegisteredCandidate(id):session?.result?.candidates.find(c=>c.id===id);
 const historicalNotice=historical?'<p class="subtle small">이전 응답 당시 선택 근거</p>'+
  (session.result.scope_note?'<p class="subtle small">'+esc(session.result.scope_note)+'</p>':'')+
  (p.proposal_unavailable_reason?'<p class="candidate-boundary">'+esc(p.proposal_unavailable_reason)+'</p>':''):'';
 const profileNotice=!historical&&candidate?.profile_only?'<p class="subtle small">전체 등록 이력 · 이번 조건의 수행 근거로 확인된 목록 아님</p>':'';
 const requestContext=registered?registeredContextHtml(candidate):candidateContextHtml(candidate);
  const reasonDetails=!requestContext&&typeof candidate?.reason==="string"&&candidate.reason.trim()?'<section class="detail-record"><h3>이번 조회 설명</h3><p>'+esc(candidate.reason)+'</p></section>':'';
 $("detailContent").innerHTML=(registered?registeredRequestAction(candidate):detailRequestAction(currentDetailCandidate(id)))+historicalNotice+profileNotice+(profile||'<h2>'+esc(p.name)+'</h2><p class="subtle">'+esc(p.org)+'</p>')+requestContext+reasonDetails+'<p class="small">'+(historical?"저장된 응답의 일부 근거이며 현재 전체 등록 이력이 아닙니다.":p.virtual?"시연용 가상 인물":p.evidence?.length?"전체 등록 이력 · 개인 수행·본인 확인·연락 의향 미확인":"등록 프로필 · 연결된 수행 기록 없음")+'</p>'+(p.evidence||[]).map(e=>'<section class="detail-record"><h3>'+esc(e.title)+'</h3><p>'+esc(e.date)+" · "+esc(e.role)+" · "+esc(e.scope)+'</p><p>'+esc(e.boundary)+'</p>'+(safeUrl(e.url)?'<a href="'+esc(e.url)+'" target="_blank" rel="noopener noreferrer">원문 출처 ↗</a>':"")+extraRecordSources(e)+'</section>').join("");
 $("detailDialog").dataset.registeredReview=String(registered);$("detailDialog").dataset.registeredBinding=registeredKey||"";modal("detailDialog",opener);$("detailDialog").scrollTop=0;
}
// Person card: a map node or drawn card opens the person's card first; a tap flips it
// to the request details, and the full dossier stays one button away.
async function openPersonCard(id,opener=document.activeElement){
 const candidate=session?.result?.candidates?.find(c=>c.id===id)||null;
 const historical=Boolean(candidate&&session?.result?.historical_result);
 let person=null;
 if(!historical){try{person=await api("/api/person?id="+encodeURIComponent(id));}catch{person=null;}}
 if(person&&person.id!==id)person=null;
 const profile=(person?person.profile:candidate?.profile)||{};
 const name=profile.display_name||person?.name||candidate?.name||"이름 미확인";
 const org=typeof person?.org==="string"?person.org:typeof candidate?.org==="string"?candidate.org:"";
 const portrait=cardPortrait(profile.portrait?.path),capability=cardCapability({profile});
 const relation=candidatePurposeRelation(candidate),label=candidatePurposeLabel(candidate);
 const reason=typeof candidate?.reason==="string"?candidate.reason.trim():"";
 const evidence=(Array.isArray(candidate?.evidence)?candidate.evidence:[]).filter(e=>e&&typeof e==="object").slice(0,3);
 const request=currentDetailCandidate(id),allowed=canPropose(request);
 const unavailable=typeof request?.proposal_unavailable_reason==="string"&&request.proposal_unavailable_reason.trim()?request.proposal_unavailable_reason:"전체 약력에서 근거를 확인해 주세요.";
 $("personCardHost").innerHTML='<div class="pc-card"'+(relation?' data-relation="'+relation+'"':'')+'><div class="pc-turn">'+
  '<button type="button" class="pc-face pc-front" aria-label="'+esc(name)+' 카드, 눌러서 상세 보기">'+
   (label?'<span class="pc-badge">'+esc(label)+'</span>':'')+
   '<span class="pc-name">'+esc(name)+'</span>'+
   '<span class="pc-portrait">'+(portrait?'<img src="'+esc(portrait)+'" alt="" decoding="async">':'<span class="pc-portrait-empty">초상 미제공</span>')+'</span>'+
   (org?'<span class="pc-org">'+esc(org)+'</span>':'')+
   '<span class="pc-capability">'+esc(capability)+'</span>'+
   '<span class="pc-hint" aria-hidden="true">눌러서 뒤집기 ↻</span><span class="pc-foil" aria-hidden="true"></span>'+
  '</button>'+
  '<div class="pc-face pc-back" aria-hidden="true" inert>'+
   '<p class="pc-back-name" tabindex="-1">'+esc(name)+'</p>'+
   (relation?'<section><h3>이번 요청과의 연결</h3><p class="pc-label">'+esc(label)+'</p>'+(reason?'<p class="pc-reason">'+esc(reason)+'</p>':'')+'</section>':'<section><p class="pc-reason">이번 요청의 후보 목록에 없는 인물이에요.</p></section>')+
   (evidence.length?'<section><h3>핵심 근거</h3><ul>'+evidence.map(e=>'<li><strong>'+esc(e.title||e.id||"연결 근거")+'</strong>'+(e.scope_label||e.scope?'<span>'+esc(e.scope_label||e.scope)+'</span>':'')+'</li>').join('')+'</ul></section>':'')+
   '<div class="pc-actions">'+(allowed?'<button type="button" class="primary" data-action="letter" data-id="'+esc(id)+'">나의 의뢰 보내기 ↗</button>':'<p class="pc-note">'+esc(unavailable)+'</p>')+
    '<button type="button" class="pc-full">전체 약력 보기</button><button type="button" class="pc-unflip">앞면 보기 ↺</button></div>'+
  '</div></div></div>';
 const card=$("personCardHost").querySelector(".pc-card"),front=card.querySelector(".pc-front"),back=card.querySelector(".pc-back");
 const quiet=RndCraft.quiet();card.classList.toggle("pc-quiet",quiet);
 const flip=on=>{card.classList.toggle("is-flipped",on);front.inert=on;front.setAttribute("aria-hidden",String(on));back.inert=!on;back.setAttribute("aria-hidden",String(!on));(on?back.querySelector(".pc-back-name"):front).focus({preventScroll:true});};
 front.addEventListener("click",()=>flip(true));
 back.querySelector(".pc-unflip").addEventListener("click",()=>flip(false));
 back.querySelector(".pc-full").addEventListener("click",()=>showPerson(id,opener).catch(exc=>error(exc.message)));
 if(!quiet){
  const rest=()=>{card.style.setProperty("--rx","0deg");card.style.setProperty("--ry","0deg");card.classList.remove("is-lit");};
  card.addEventListener("pointermove",e=>{const r=card.getBoundingClientRect(),x=Math.min(1,Math.max(0,(e.clientX-r.left)/r.width)),y=Math.min(1,Math.max(0,(e.clientY-r.top)/r.height));
   card.style.setProperty("--mx",(x*100).toFixed(1)+"%");card.style.setProperty("--my",(y*100).toFixed(1)+"%");
   card.style.setProperty("--rx",((.5-y)*12).toFixed(2)+"deg");card.style.setProperty("--ry",((x-.5)*16).toFixed(2)+"deg");card.classList.add("is-lit");});
  card.addEventListener("pointerleave",rest);card.addEventListener("pointercancel",rest);card.addEventListener("pointerup",e=>{if(e.pointerType!=="mouse")rest();});
 }
 const dialog=$("personCardDialog");
 if(!dialog.backdropCloseBound){dialog.addEventListener("click",e=>{if(e.target===dialog)dialog.close();});dialog.backdropCloseBound=true;}
 modal("personCardDialog",opener);front.focus({preventScroll:true});
}
// A failed draft remains in the currently open person dialog; no draft or send is simulated.
function detailRequestDraftError(message,button){
 const dialog=$("detailDialog");
 if(!dialog?.open||!button?.isConnected||!dialog.contains(button))return false;
 let notice=dialog.querySelector("[data-request-draft-error]");
 if(!message){if(notice)notice.remove();return true;}
 if(!notice){
  notice=document.createElement("p");notice.setAttribute("data-request-draft-error","");
  notice.className="response-error";notice.setAttribute("role","alert");
  notice.setAttribute("aria-label","의뢰서 열기 오류");notice.setAttribute("tabindex","-1");
  button.after(notice);
 }
 notice.textContent="의뢰서를 열지 못했어요. "+displayError(String(message));
 notice.focus({preventScroll:true});notice.scrollIntoView({block:"nearest",behavior:"instant"});
 return true;
}
// These are server-generated review bodies from this exact prepared response.
// They never authorize saving or sending a proposal.
function preparedLetterDrafts(ids){
 const preview=session?.draft_previews,scout=session?.scout;
 if(!preview||!session.ready||session.pending||!scout?.disclosed||!scout.revision||
    scout.revision!==session.discovery?.revision||scout.revision!==session.prepared_discovery_revision||
    preview.session_id!==session.id||preview.revision!==scout.revision||
    !Array.isArray(preview.items)||preview.items.length>7||!Array.isArray(ids)||ids.length>7)return null;
 const drafts=[];
 for(const id of ids){
  const candidate=currentDetailCandidate(id),matches=preview.items.filter(item=>item?.candidate?.id===id);
  if(!canPropose(candidate)||matches.length!==1)return null;
  const draft=matches[0];
  if(draft.session_id!==session.id||draft.candidate.name!==candidate.name||
     typeof draft.body!=="string"||!draft.body.trim()||draft.body.length>30000)return null;
  drafts.push(JSON.parse(JSON.stringify(draft)));
 }
 return drafts;
}
async function openLetter(ids,registered=false){
 if(registered){if(!Array.isArray(ids)||ids.length!==1)throw new Error("등록 후보 한 명을 선택해 주세요.");return openRegisteredLetter(ids[0]);}
 registeredLetterTicket++;checkProposalSelection(ids);
 const source=session,revision=source.scout?.revision,candidateContexts=captureCandidateContexts(source,ids);
 if(source.pending||(revision&&ids.some(id=>!canPropose(currentDetailCandidate(id)))))throw new Error("대화 조건이 바뀌었어요. 현재 추천 인물에서 의뢰서를 다시 열어 주세요.");
 const drafts=preparedLetterDrafts(ids)||await Promise.all(ids.map(id=>api("/api/draft",{session_id:source.id,candidate_id:id})));
 if(accountNavigationPending||accountInvalidated||session!==source||session.pending||session.scout?.revision!==revision)
  throw new Error("대화 조건이 바뀌었어요. 현재 추천 인물에서 의뢰서를 다시 열어 주세요.");
 checkProposalSelection(ids);
 if(revision&&ids.some(id=>!canPropose(currentDetailCandidate(id))))throw new Error("현재 추천 인물에서 의뢰서를 다시 열어 주세요.");
 letter={ids,drafts,key:crypto.randomUUID(),sessionId:source.id,index:0,candidateContexts,bodies:Object.fromEntries(drafts.map(d=>[d.candidate.id,d.body]))};
 renderLetter();modal("letterDialog");
}
function renderLetter(){const registered=letter.kind==="registered_review";$("draftButton").disabled=registered;$("proposeButton").disabled=registered;$("letterBody").readOnly=registered;$("letterDialog").querySelector("p.subtle").textContent=registered?"검토용 초안 · 현재 저장·발송 권한이 없습니다. 수행 가능 여부와 연락 의향은 미확인입니다.":publicMode?"이 방문자의 제안함에 시연 기록으로 저장됩니다. 실제 수신자에게 연락하지 않습니다.":"이 기기의 제안함에 시연 기록으로 저장됩니다. 실제 수신자에게 연락하지 않습니다.";const d=letter.drafts[letter.index];renderLetterCandidateContext(d.candidate.id);$("letterTitle").textContent=d.candidate.name+"님에게";$("letterBody").value=letter.bodies[d.candidate.id];$("letterError").textContent="";let switcher=$("recipientSelect");if(switcher)switcher.remove();if(letter.ids.length>1){switcher=document.createElement("select");switcher.id="recipientSelect";switcher.setAttribute("aria-label","경로별 수신자");switcher.innerHTML=letter.drafts.map((x,i)=>'<option value="'+i+'"'+(i===letter.index?' selected':'')+'>'+esc((i+1)+". "+x.candidate.name)+'</option>').join("");$("letterBody").before(switcher);switcher.addEventListener("change",()=>{keepLetter();letter.index=Number(switcher.value);renderLetter();});}}
function keepLetter(){const id=letter.ids[letter.index];if(letter.bodies[id]!==$("letterBody").value){letter.bodies[id]=$("letterBody").value;letter.key=crypto.randomUUID();}}
async function saveLetter(state){if(letter?.kind==="registered_review"){$("letterError").textContent="등록 전문가 초안은 검토만 가능하며 저장하거나 발송할 수 없어요.";return;}const button=state==="sent"?$("proposeButton"):$("draftButton");button.disabled=true;$("draftButton").disabled=true;$("proposeButton").disabled=true;try{keepLetter();const saved=await api("/api/proposals",{session_id:letter.sessionId,candidate_ids:letter.ids,bodies:letter.bodies,state,idempotency_key:letter.key});$("letterDialog").close();const recipientName=letter.drafts[0].candidate.name;letter=null;if(state==="sent"){RndCraft.deliver(recipientName,saved.length);if(mailDelivery)toast(deliverySummary(saved));}else toast(saved.length+"건을 제안함에 "+(state==="draft"?"초안으로":"시연 기록으로")+" 저장했어요.");}catch(e){$("letterError").textContent=e.message;}finally{$("draftButton").disabled=false;$("proposeButton").disabled=false;}}
function deliverySummary(saved){const counts={sent:0,skipped_no_address:0,failed:0,other:0};for(const p of saved){const s=p?.delivery?.status;counts[s in counts?s:"other"]++;}const parts=[];if(counts.sent)parts.push("메일 발송 "+counts.sent+"건");if(counts.skipped_no_address)parts.push("주소 미등록 "+counts.skipped_no_address+"건");if(counts.failed)parts.push("발송 실패 "+counts.failed+"건");if(counts.other)parts.push("기록만 "+counts.other+"건");return parts.join(" · ")||"제안함에 기록했어요.";}
profileUI=RndProfileChat.create({host:$("profileChatHost"),getToken:()=>token,getSessionId:()=>session?.id||null,
 onBusy:value=>{profileBusy=value;controls();},
 onClose:()=>{autoScroll=false;render();$("message").focus({preventScroll:true});},
 onSession:value=>{
  invalidateRecovery(true);session=value;updateHistory();window.history.replaceState(null,"","/?chat="+session.id);
  if(profileSubmission){if(composerInputRevision===profileSubmission.revision&&$("message").value===profileSubmission.text)setComposerDraft("");files=files.filter(f=>!profileSubmission.ids.includes(f.id));renderFiles();profileSubmission=null;}
  autoScroll=false;render();resizeInput();
 }});
window.addEventListener("rndplz:before-account-navigation",event=>{
 const state=profileUI?.accountNavigationState();event.detail.checkedScopes.push("chat");
 if(!state||accountNavigationPending||busy||profileBusy||uploading||prepareBusy||session?.pending||$("letterDialog").open||state.blocked){
  event.preventDefault();event.detail.message="진행 중인 대화·프로필·제안 작업의 결과를 먼저 확인해 주세요.";return;
 }
 if($("message").value.trim()||files.length||briefEditor||state.dirty)event.detail.dirty=true;
});
window.addEventListener("rndplz:account-navigation",event=>{
 accountNavigationPending=event.detail?.phase!=="cancel";
 if(accountNavigationPending){invalidateRegisteredUI();invalidateRecovery(true);}
 if(accountNavigationPending){drawEpoch++;drawMetadataController?.abort();drawMetadataController=null;drawController?.dispose();drawController=null;drawRenderKey="";$("proposalZone").replaceChildren();}
 if(event.detail?.phase==="invalidate"){
  accountInvalidated=true;abortAttachment();inlineMessageLinks.clear();attachmentPreviewTicket++;prepareTicket++;resetPrepareProgress();modelSelectionEpoch++;controller?.abort();token="";
 }
 controls();
 if(!accountNavigationPending&&!accountInvalidated)renderCandidates();
});
$ ("profileButton").addEventListener("click",async()=>{if(busy||profileBusy||prepareBusy||isPublicPaperContext())return;error();autoScroll=false;await profileUI.open();render();$("profileChatHost").scrollIntoView({block:"start",behavior:"instant"});});
$ ("chatForm").addEventListener("submit",e=>{e.preventDefault();submitComposer();});
$ ("message").addEventListener("paste",pasteImages);
$ ("message").addEventListener("input",()=>{invalidateRegisteredUI();composerInputRevision++;resizeInput();});
$ ("message").addEventListener("compositionstart",()=>{composerComposing=true;composerInputRevision++;});
$ ("message").addEventListener("compositionend",()=>{composerComposing=false;composerInputRevision++;controls();});
// Touch keyboards have no Shift+Enter: there Enter inserts a line break and only the send button submits.
const touchComposer=!!(window.matchMedia&&window.matchMedia("(pointer: coarse)").matches);
if(touchComposer){const keyboardHint=document.querySelector(".keyboard-hint");if(keyboardHint)keyboardHint.textContent="보내기 버튼으로 전송 · Enter 줄바꿈";}
$ ("message").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey&&!touchComposer){if(e.isComposing||composerComposing||e.keyCode===229)return;e.preventDefault();if(!composerSendLocked()&&!$("sendButton").disabled)$("chatForm").requestSubmit();}});
$ ("stopButton").addEventListener("click",()=>{invalidateRegisteredUI();controller?.abort();});
$ ("newButton").addEventListener("click",newChat);
$ ("attachButton").addEventListener("click",()=>$ ("fileInput").click());
$ ("fileInput").addEventListener("change",e=>upload([...e.target.files]));
$ ("attachmentCancel").addEventListener("click",abortAttachment);


$ ("modelSelect").addEventListener("change",e=>selectModel(e.target.value));
$ ("settingsButton").addEventListener("click",()=>modal("settingsDialog"));
$ ("historyButton").addEventListener("click",()=>{$("historyList").innerHTML=history.length?history.map(h=>'<button class="history-item" data-action="history" data-id="'+h.id+'">'+esc(h.title)+'<small>'+new Date(h.updated).toLocaleString("ko-KR")+(hasPublicPaperScope(h)?" · "+publicPaperLabel(h)+" · 공개 논문":"")+'</small></button>').join(""):'<p class="subtle">첫 대화를 시작해 보세요.</p>';modal("historyDialog");});
$ ("refreshModels").addEventListener("click",async()=>{try{if(!await refreshModelOptions())return;toast("사용 가능한 모델 목록을 갱신했어요.");}catch(e){error(e.message);}});
$ ("configForm").addEventListener("submit",async e=>{e.preventDefault();$("saveConfig").disabled=true;$("configMessage").textContent="";try{const provider=$("provider").value,epoch=modelSelectionEpoch,ticket=++modelCatalogTicket;const data=await api("/api/chat/configure",{provider,model:$("apiModel").value,key:$("apiKey").value});$("apiKey").value="";if(epoch===modelSelectionEpoch){selectedModel=provider;modelSelectionOrigin="explicit";modelSelectionEpoch++;}if(ticket===modelCatalogTicket)modelOptions(data);else{renderModelSelect();controls();}$("configMessage").textContent="설정을 저장했어요. 다음 메시지에는 현재 선택한 모델을 사용합니다.";}catch(e){$("configMessage").textContent=e.message;}finally{$("saveConfig").disabled=false;}});
$ ("draftButton").addEventListener("click",()=>saveLetter("draft"));
$ ("proposeButton").addEventListener("click",()=>saveLetter("sent"));
document.addEventListener("click",async e=>{const button=e.target.closest("button");if(!button)return;if(button.classList.contains("close")){const dialog=button.closest("dialog");if(dialog?.dataset.registeredReview==="true"||(dialog?.id==="letterDialog"&&letter?.kind==="registered_review"))invalidateRegisteredUI();dialog.close();return;}const action=button.dataset.action,id=button.dataset.id;if(!action||composerClientLocked())return;
 try{
  if(action==="profile-receipt"){autoScroll=false;if(button.dataset.version)await profileUI.showReceipt(Number(button.dataset.version));else await profileUI.open();render();$("profileChatHost").scrollIntoView({block:"start",behavior:"instant"});}
 else if(action==="remove-file"){removeAttachment(id);}
 else if(action==="preview-file"){await previewAttachment(id,button);}
  else if(action==="history"){
   invalidateRegisteredUI();attachmentPreviewTicket++;prepareTicket++;profileUI.close();
   const epoch=modelSelectionEpoch,previousSession=session,previousSessionId=session?.id,priorRecovery=invalidateRecovery(),navigationEpoch=recoveryEpoch;
   try{
    const saved=await api("/api/chat/session?id="+id);
    if(navigationEpoch!==recoveryEpoch||accountNavigationPending||accountInvalidated)return;
    session=saved;restoreRecoveryAfterHistory(priorRecovery,saved);restoreModelSelection(session,epoch);
    if(session.id!==previousSessionId){files=[];inlineMessageLinks.clear();setComposerDraft("");}renderFiles();$("historyDialog").close();window.history.replaceState(null,"","/?chat="+id);autoScroll=true;render();
   }catch(e){
    if(navigationEpoch!==recoveryEpoch||accountNavigationPending||accountInvalidated||session!==previousSession)return;
    restoreRecoveryAfterHistoryFailure(priorRecovery,previousSession,navigationEpoch);
    if(!$("composerError").textContent)error(e.message);
   }finally{if(navigationEpoch===recoveryEpoch)attachmentPreviewTicket++;}
  }
  else if(action==="recovery-status")await recoverSavedTurn(recoveryState);
  else if(action==="retry")await retryTurn(id);
  else if(action==="prepare")await prepareDiscovery(button,e.detail===0);
  else if(action==="person-select"){const choice=session.result?.choices?.find(c=>c.id===id);if(!choice)throw new Error("표시된 인물을 다시 선택해 주세요.");await send({text:choice.name+"의 이력 보여줘",person_id:id,session_id:session.id,model_id:selectedModel,model_selection_origin:modelSelectionOrigin,turn_id:crypto.randomUUID()});}
  else if(action==="registered-person")await showPerson(id,button,true);
  else if(action==="registered-letter"){detailRequestDraftError("",button);await openLetter([id],true);}
  else if(action==="person")await showPerson(id,button);
  else if(action==="letter"){detailRequestDraftError("",button);await openLetter([id]);}
  else if(action==="route-letter"){const ids=session?.result?.intent==="person_lookup"?[]:(session?.result?.candidates||[]).filter(canPropose).map(c=>c.id);if(ids.length)await openLetter(ids);}
 }catch(e){if(!["letter","registered-letter"].includes(action)||!detailRequestDraftError(e.message,button))error(e.message);button.disabled=false;}
});
window.addEventListener("scroll",()=>{autoScroll=document.documentElement.scrollHeight-innerHeight-scrollY<160;},{passive:true});
var mailDelivery=false;
(async()=>{try{const ticket=++modelCatalogTicket,data=await api("/api/chat/bootstrap");token=data.token;history=data.history;mailDelivery=Boolean(data.mail_delivery&&data.mail_delivery.enabled===true);if(ticket===modelCatalogTicket)modelOptions(data);const id=new URLSearchParams(location.search).get("chat");if(id){const epoch=modelSelectionEpoch;session=await api("/api/chat/session?id="+encodeURIComponent(id));restoreModelSelection(session,epoch);}render();resizeInput();if(new URLSearchParams(location.search).has("settings"))modal("settingsDialog");}catch(e){error(e.message);}})();
