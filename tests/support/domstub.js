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

// ---- Leaflet, enough of it to exercise the map's real code path -----------
// Without this, initMap() returns early on `typeof L === "undefined"`, drawMap()
// does nothing, and the map tests pass while testing nothing at all - the same
// trap as the planner that was silently parsed as CSS.
globalThis.__leaflet = { markers: [], circles: [], tileLayers: [], fits: 0, pans: 0 };
class LayerGroup {
  constructor(){ this._layers = []; }
  addTo(){ return this; }
  clearLayers(){ this._layers.length = 0;
    globalThis.__leaflet.markers = globalThis.__leaflet.markers
      .filter(m => m._group !== this); return this; }
  addLayer(l){ this._layers.push(l); return this; }
}
class Marker {
  constructor(latlng, opts){ this._latlng = latlng; this.options = opts || {};
    this._on = {}; }
  addTo(g){ if (g && g._layers) { g._layers.push(this); this._group = g; }
    globalThis.__leaflet.markers.push(this); return this; }
  bindTooltip(t){ this._tip = t; return this; }
  on(ev, fn){ (this._on[ev] ||= []).push(fn); return this; }
  fire(ev){ (this._on[ev] || []).forEach(f => f()); }
  setStyle(o){ Object.assign(this.options, o); return this; }
  bringToFront(){ return this; }
  getLatLng(){ return this._latlng; }
}
globalThis.L = {
  map(){ return {
    fitBounds(){ globalThis.__leaflet.fits++; },
    panTo(){ globalThis.__leaflet.pans++; },
    setView(){},
  }; },
  tileLayer(url, opts){ globalThis.__leaflet.tileLayers.push({ url, opts });
    return { addTo(){ return this; } }; },
  control: { layers(){ return { addTo(){ return this; } }; } },
  layerGroup(){ const g = new LayerGroup(); return g; },
  circle(latlng, opts){ const c = new Marker(latlng, opts);
    globalThis.__leaflet.circles.push(c); return c; },
  circleMarker(latlng, opts){ return new Marker(latlng, opts); },
  latLngBounds(pts){ return { pts }; },
};
