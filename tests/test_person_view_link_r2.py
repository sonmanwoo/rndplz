"""Profile participant links reuse the current public map's person-opening path."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


WEB = Path(__file__).resolve().parents[1] / "rndplz" / "web"


def test_profile_participant_link_opens_only_current_public_map_people():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for shared person-view checks")
    source = (WEB / "app.js").read_text(encoding="utf-8")
    start = source.index("async function openLinkedPerson()")
    end = source.index("async function openDetailRecord", start)
    helper = source[start:end]
    # A bad link uses the usual action error path; it must not fail map bootstrap.
    assert 'await showTab("map")' in source
    assert "await task(openLinkedPerson);" in source
    script = r"""
const assert=require('node:assert/strict'),vm=require('node:vm');
const helper=HELPER;
async function check(search,mobile,available=true,mapExists=true){
 const calls=[],host={},request=()=>{},map={
  found:id=>{calls.push(['found',id]);return available?{recordIds:['R']}:null;},
  select:id=>calls.push(['select',id])
 };
 const context={URLSearchParams,location:{search},SHEET_MEDIA:{matches:mobile},
  $:id=>{assert.equal(id,'peopleMapHost');return host;},api:request,
  RndPeopleMap:{ensure:async(got,api)=>{assert.equal(got,host);assert.equal(api,request);calls.push(['ensure']);return mapExists?map:null;}},
  rememberDetailTrigger:(trigger,id)=>{assert.equal(trigger,null);calls.push(['trigger',id]);},
  openMapPerson:async(id,controller,mode)=>{assert.equal(controller,map);calls.push(['open',id,mode]);}
 };
 vm.runInNewContext(helper,context);
 let error;
 try{await context.openLinkedPerson();}catch(e){error=e;}
 return {calls,error};
}
(async()=>{
 assert.deepEqual((await check('',false)).calls,[]);
 assert.deepEqual((await check('?person=',false)).calls,[]);
 for(const mobile of [false,true]){
  const {calls,error}=await check('?person=PUBLIC%2B1',mobile);
  assert.equal(error,undefined);
  assert.deepEqual(calls,[['ensure'],['found','PUBLIC+1'],['select','PUBLIC+1'],['trigger','PUBLIC+1'],['open','PUBLIC+1',mobile?'full':null]]);
 }
 const missing=await check('?person=UNKNOWN',false,false);
 assert(missing.error);assert.deepEqual(missing.calls,[['ensure'],['found','UNKNOWN']]);
 const unavailable=await check('?person=PUBLIC',true,true,false);
 assert(unavailable.error);assert.deepEqual(unavailable.calls,[['ensure']]);
})().catch(error=>{console.error(error);process.exitCode=1;});
""".replace("HELPER", json.dumps(helper, ensure_ascii=True))
    completed = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8")
    assert completed.returncode == 0, completed.stdout + completed.stderr
