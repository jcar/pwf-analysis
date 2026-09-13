// Minimal DOM good enough to exercise the render paths and surface real errors.
class N {
  constructor(tag){ this.tagName=tag; this.children=[]; this.attrs={}; this.style={};
    this._classes=new Set(); this._text=""; this._on={};
    // dataset writes must land in attrs: the page sets `tr.dataset.lake` and
    // then reads it back with getAttribute("data-lake"), and a stub that kept
    // the two apart would pass a test the real DOM fails.
    const self=this;
    this.dataset=new Proxy({}, {
      set(_t,k,v){ self.attrs["data-"+String(k).replace(/[A-Z]/g,m=>"-"+m.toLowerCase())]=v; return true; },
      get(_t,k){ return self.attrs["data-"+String(k).replace(/[A-Z]/g,m=>"-"+m.toLowerCase())]; },
    });
    this.classList={
      add:(...c)=>c.forEach(x=>self._classes.add(x)),
      remove:(...c)=>c.forEach(x=>self._classes.delete(x)),
      contains:c=>self._classes.has(c),
      toggle:(c,force)=>{ const on = force===undefined ? !self._classes.has(c) : !!force;
        if(on) self._classes.add(c); else self._classes.delete(c); return on; },
    };
  }
  append(...k){ k.forEach(x=>this.children.push(x)); }
  setAttribute(k,v){ this.attrs[k]=v; }
  removeAttribute(k){ delete this.attrs[k]; }
  getAttribute(k){ return this.attrs[k]; }
  addEventListener(type, fn){ (this._on[type] ||= []).push(fn); }
  dispatch(type){ (this._on[type]||[]).forEach(fn=>fn({target:this})); }
  querySelectorAll(){ return []; }
  querySelector(){ return null; }
  insertRow(){ const r=track(new N("tr"));
    r.insertCell=()=>{const c=track(new N("td")); r.children.push(c); return c;};
    this.children.push(r); return r; }
  createTHead(){ const t=track(new N("thead")); this.children.push(t);
    t.insertRow=()=>{const r=track(new N("tr")); t.children.push(r); return r;}; return t; }
  createTBody(){ const t=track(new N("tbody")); this.children.push(t);
    t.insertRow=()=>{const r=track(new N("tr"));
      r.insertCell=()=>{const c=track(new N("td")); r.children.push(c); return c;};
      t.children.push(r); return r;}; return t; }
  get textContent(){ return this._text; }
  set textContent(v){ this._text=v; this.children=[]; }
  set innerHTML(v){ this._html=v; }
  get innerHTML(){ return this._html||""; }
  scrollIntoView(){}
  set hidden(v){}
}
const made=[];
function track(n){ made.push(n); return n; }
globalThis.document={
  createElement:t=>{const n=new N(t); made.push(n); return n;},
  createElementNS:(ns,t)=>{const n=new N(t); made.push(n); return n;},
  createTextNode:t=>{const n=new N("#text"); n._text=t; return n;},
  getElementById:id=>{const n=new N("div"); n.id=id; made.push(n); return n;},
  querySelector:sel=>{const n=new N("div"); n.id=(sel||"").replace("#",""); made.push(n); return n;},
  body:{classList:{add(){},remove(){}}},
};
// Real enough to resolve "[data-lake]", which the linked hover depends on.
// A stub returning [] made the hover test pass while doing nothing at all -
// the same failure mode as the planner that was silently parsed as CSS.
globalThis.document.querySelectorAll=(sel)=>{
  if(sel==="[data-lake]") return made.filter(n=>n.attrs && n.attrs["data-lake"]!=null);
  return [];
};
globalThis.window={addEventListener(){},scrollTo(){}};
globalThis.location={hash:""};
globalThis.__made=made;

// Record which render paths actually ran, so a test can assert the planner
// built something rather than merely that the file parsed.
globalThis.__drew = {};
const _cens = globalThis.document.createElementNS;
globalThis.document.createElementNS = (ns, t) => {
  if (t === "path") globalThis.__drew.map = true;
  return _cens(ns, t);
};
const _qs = globalThis.document.querySelector;
globalThis.document.querySelector = (sel) => {
  if (sel === "#brief") globalThis.__drew.brief = true;
  return _qs(sel);
};
