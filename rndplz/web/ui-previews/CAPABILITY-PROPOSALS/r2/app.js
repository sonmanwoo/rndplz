import {data} from './data.js';
import {initMap} from './map.js';
import {initProposals} from './proposals.js';
initMap(document.querySelector('#map-root'),data);
const proposalsView=initProposals(document.querySelector('#proposals-root'));
const tabs=[...document.querySelectorAll('[data-screen]')];
function show(screen){
  const active=screen==='proposals'?'proposals':'map';
  tabs.forEach(tab=>{const selected=tab.dataset.screen===active;tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;document.getElementById(`${tab.dataset.screen}-panel`).hidden=!selected;});
  proposalsView.setVisible(active==='proposals');
}
tabs.forEach((tab,i)=>{tab.addEventListener('click',()=>{show(tab.dataset.screen);history.replaceState(null,'',`#${tab.dataset.screen}`)});tab.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const index=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[index].click();tabs[index].focus();});});
window.addEventListener('hashchange',()=>{const screen=location.hash.slice(1);if(screen==='map'||screen==='proposals')show(screen);});
show(location.hash.slice(1));
