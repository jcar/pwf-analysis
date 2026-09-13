// Minimal DOM good enough to exercise the render paths and surface real errors.
class N {
  constructor(tag){ this.tagName=tag; this.children=[]; this.attrs={}; this.style={};
    this.dataset={}; this.classList={add(){},remove(){}}; this._text=""; }
  append(...k){ k.forEach(x=>this.children.push(x)); }
  setAttribute(k,v){ this.attrs[k]=v; }
  removeAttribute(k){ delete this.attrs[k]; }
  getAttribute(k){ return this.attrs[k]; }
  addEventListener(){}
  querySelectorAll(){ return []; }
  querySelector(){ return null; }
  insertRow(){ const r=new N("tr"); r.insertCell=()=>{const c=new N("td"); r.children.push(c); return c;};
    this.children.push(r); return r; }
  createTHead(){ const t=new N("thead"); this.children.push(t);
    t.insertRow=()=>{const r=new N("tr"); t.children.push(r); return r;}; return t; }
  createTBody(){ const t=new N("tbody"); this.children.push(t);
    t.insertRow=()=>{const r=new N("tr"); r.insertCell=()=>{const c=new N("td"); r.children.push(c); return c;};
      t.children.push(r); return r;}; return t; }
  get textContent(){ return this._text; }
  set textContent(v){ this._text=v; this.children=[]; }
  set innerHTML(v){ this._html=v; }
  get innerHTML(){ return this._html||""; }
  scrollIntoView(){}
  set hidden(v){}
}
const made=[];
globalThis.document={
  createElement:t=>{const n=new N(t); made.push(n); return n;},
  createElementNS:(ns,t)=>{const n=new N(t); made.push(n); return n;},
  createTextNode:t=>{const n=new N("#text"); n._text=t; return n;},
  getElementById:id=>{const n=new N("div"); n.id=id; made.push(n); return n;},
  querySelector:sel=>{const n=new N("div"); n.id=(sel||"").replace("#",""); made.push(n); return n;},
  body:{classList:{add(){},remove(){}}},
};
globalThis.window={addEventListener(){},scrollTo(){}};
globalThis.location={hash:""};
globalThis.__made=made;
