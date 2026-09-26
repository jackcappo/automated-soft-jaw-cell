/* Minimal binary/ASCII STL reader for the simulator (no loader plugins needed).
 * Returns { positions: Float32Array (xyz per vertex, 3 vertices per triangle), count }. */
(function (root) {
  function parse(buffer) {
    const bytes = new Uint8Array(buffer);
    const dv = new DataView(buffer);
    if (bytes.length >= 84) {
      const n = dv.getUint32(80, true);
      if (84 + n * 50 === bytes.length) {
        const pos = new Float32Array(n * 9);
        for (let i = 0; i < n; i++) {
          const o = 84 + i * 50 + 12;
          for (let k = 0; k < 9; k++) pos[i * 9 + k] = dv.getFloat32(o + k * 4, true);
        }
        return { positions: pos, count: n };
      }
    }
    const text = new TextDecoder().decode(bytes);
    const v = [];
    for (const m of text.matchAll(/vertex\s+(\S+)\s+(\S+)\s+(\S+)/g)) v.push(+m[1], +m[2], +m[3]);
    if (!v.length || v.length % 9) throw new Error("not a valid STL");
    return { positions: new Float32Array(v), count: v.length / 9 };
  }
  function fromBase64(b64) {
    const bin = typeof atob === "function" ? atob(b64) : Buffer.from(b64, "base64").toString("binary");
    const buf = new ArrayBuffer(bin.length), u = new Uint8Array(buf);
    for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
    return buf;
  }
  const api = { parse, fromBase64 };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SoftJawStl = api;
})(typeof window !== "undefined" ? window : globalThis);
