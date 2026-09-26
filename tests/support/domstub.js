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
  // A real classList: the app toggles mode-map / mode-plan / profile-open on
  // the body, and a stub with only add/remove let a mode switch throw.
  body: (() => { const b = new N("body"); return b; })(),
};
// Real enough to resolve "[data-lake]", which the linked hover depends on.
// A stub returning [] made the hover test pass while doing nothing at all -
// the same failure mode as the planner that was silently parsed as CSS.
globalThis.document.querySelectorAll=(sel)=>{
  if(sel==="[data-lake]") return made.filter(n=>n.attrs && n.attrs["data-lake"]!=null);
  return [];
};
globalThis.window={addEventListener(){},scrollTo(){}};
globalThis.requestAnimationFrame=fn=>fn();
globalThis.setTimeout=globalThis.setTimeout||((fn)=>fn());
globalThis.getComputedStyle=()=>({getPropertyValue:()=>""});
globalThis.history={state:null,scrollRestoration:"auto",
  pushState(s,_t,h){this.state=s; if(h) globalThis.location.hash=h.replace(/^[^#]*/,"");},
  replaceState(s,_t,h){this.state=s; if(h) globalThis.location.hash=h.replace(/^[^#]*/,"");},
  back(){}};
globalThis.sessionStorage={_d:{},getItem(k){return this._d[k]??null;},
  setItem(k,v){this._d[k]=String(v);},removeItem(k){delete this._d[k];}};
globalThis.URLSearchParams=globalThis.URLSearchParams||class{};
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

// ---- MapLibre GL, enough of it to exercise the map's real code path -------
// Without this, initMap() returns early on `typeof maplibregl === "undefined"`,
// drawMap() does nothing, and the map tests pass while testing nothing at all -
// the same trap as the planner that was silently parsed as CSS, and as the
// Leaflet stub that returned [] from querySelectorAll.
globalThis.__gl = { sources: {}, layers: [], filters: {}, paint: {},
                    controls: [], eases: 0, fits: 0, resizes: 0, style: null };

class GLSource {
  constructor(spec){ this.spec = spec; this.data = spec && spec.data; }
  setData(d){ this.data = d; }
}
class GLMap {
  constructor(opts){
    this.opts = opts || {};
    globalThis.__gl.style = this.opts.style;
    this._on = {};
    this._center = { lng: (opts.center||[0,0])[0], lat: (opts.center||[0,0])[1] };
    this._zoom = opts.zoom ?? 6;
  }
  // The real map fires "load" once its style is ready. Nothing drives a frame
  // here, so a load handler runs the moment it is registered - otherwise
  // applyAppLayers never runs and the map tests pass against an empty map.
  on(ev, a, b){ const fn = b || a; (this._on[ev] ||= []).push(fn);
    if (ev === "load") fn({});
    return this; }
  once(ev, fn){ return this.on(ev, fn); }
  off(){ return this; }
  fire(ev, payload){ (this._on[ev]||[]).forEach(f => f(payload || {})); }
  addControl(c){ globalThis.__gl.controls.push(c); return this; }
  addSource(id, spec){ globalThis.__gl.sources[id] = new GLSource(spec); }
  getSource(id){ return globalThis.__gl.sources[id]; }
  removeSource(id){ delete globalThis.__gl.sources[id]; }
  addLayer(spec){ globalThis.__gl.layers.push(spec);
    if (spec.paint) globalThis.__gl.paint[spec.id] = { ...spec.paint }; }
  getLayer(id){ return globalThis.__gl.layers.find(l => l.id === id); }
  removeLayer(id){ globalThis.__gl.layers =
    globalThis.__gl.layers.filter(l => l.id !== id); }
  setFilter(id, f){ globalThis.__gl.filters[id] = f; }
  getFilter(id){ return globalThis.__gl.filters[id]; }
  setPaintProperty(id, k, v){ (globalThis.__gl.paint[id] ||= {})[k] = v; }
  setLayoutProperty(){}
  setStyle(s){ globalThis.__gl.style = s; this.fire("styledata"); }
  easeTo(o){ globalThis.__gl.eases++; if (o && o.center){
    this._center = { lng: o.center[0], lat: o.center[1] }; }
    if (o && o.zoom != null) this._zoom = o.zoom; }
  jumpTo(o){ this.easeTo(o); }
  flyTo(o){ this.easeTo(o); }
  fitBounds(){ globalThis.__gl.fits++; }
  resize(){ globalThis.__gl.resizes++; }
  getCenter(){ return this._center; }
  getZoom(){ return this._zoom; }
  getBearing(){ return 0; }
  getPitch(){ return 0; }
  getCanvas(){ return { style: {} }; }
  getContainer(){ return { style: {} }; }
  queryRenderedFeatures(){ return []; }
  remove(){}
}
globalThis.maplibregl = {
  Map: GLMap,
  NavigationControl: class { constructor(o){ this.kind = "nav"; this.o = o; } },
  ScaleControl: class { constructor(o){ this.kind = "scale"; this.o = o; } },
  GeolocateControl: class { constructor(o){ this.kind = "geo"; this.o = o; } },
  AttributionControl: class { constructor(o){ this.kind = "attr"; this.o = o; } },
  LngLatBounds: class { constructor(){ this.pts = []; }
    extend(p){ this.pts.push(p); return this; } },
  supported: () => true,
};
