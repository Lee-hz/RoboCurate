export function nearestFrame(times, seconds) {
  if (!times.length) return -1;
  let lo = 0,
    hi = times.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid] < seconds) lo = mid + 1;
    else hi = mid;
  }
  if (lo === times.length) return lo - 1;
  return lo > 0 && seconds - times[lo - 1] <= times[lo] - seconds ? lo - 1 : lo;
}
export function adjacentFrame(times, seconds, direction, currentIndex = null) {
  const i =
    Number.isInteger(currentIndex) && times[currentIndex] === seconds
      ? currentIndex
      : nearestFrame(times, seconds);
  return i < 0 ? -1 : Math.max(0, Math.min(times.length - 1, i + direction));
}
export function clampWindow(start, end, duration, minSpan = 0.1) {
  if (![start, end, duration].every(Number.isFinite) || duration <= 0)
    return [0, 0];
  if (end < start) [start, end] = [end, start];
  const span = Math.min(duration, Math.max(minSpan, end - start));
  start = Math.max(0, Math.min(start, duration - span));
  return [start, start + span];
}
export function zoomWindow(window, anchor, factor, duration) {
  const [a, b] = window,
    ratio = (anchor - a) / Math.max(b - a, 0.001),
    span = (b - a) * factor;
  return clampWindow(
    anchor - span * ratio,
    anchor + span * (1 - ratio),
    duration,
  );
}
export function parseFrameBatch(buffer) {
  if (buffer.byteLength < 4) throw Error("图像批次不完整");
  const size = new DataView(buffer).getUint32(0, true);
  if (size > 65536 || size + 4 > buffer.byteLength)
    throw Error("图像批次头部无效");
  const header = JSON.parse(
    new TextDecoder().decode(new Uint8Array(buffer, 4, size)),
  );
  let offset = 4 + size;
  const frames = header.frames.map((frame) => {
    if (
      !Number.isInteger(frame.size) ||
      frame.size < 0 ||
      offset + frame.size > buffer.byteLength
    )
      throw Error("图像批次长度无效");
    const blob = new Blob([new Uint8Array(buffer, offset, frame.size)], {
      type: "image/jpeg",
    });
    offset += frame.size;
    return { ...frame, blob };
  });
  if (offset !== buffer.byteLength) throw Error("图像批次包含多余字节");
  return { token: header.token, frames };
}

export class FramePlayer {
  constructor(ep, { status = () => {}, painted = () => {}, root = document, indexUrl = null } = {}) {
    this.ep = ep;
    this.status = status;
    this.onPainted = painted;
    this.root = root;
    this.indexUrl = indexUrl || '/api/frame-index?ep=' + ep;
    this.alive = true;
    this.index = null;
    this.time = 0;
    this.cache = new Map();
    this.busy = new Map();
    this.requests = new Map();
    this.last = new Map();
    this.prefetch = false;
    this.failed = new Set();
    this.displayBusy = new Set();
    this.exact = null;
  }
  async load() {
    this.status("正在读取帧索引…");
    const r = await fetch(this.indexUrl);
    if (!r.ok) throw Error((await r.json()).error || "帧索引读取失败");
    const index = await r.json();
    if (!this.alive) return;
    this.index = index;
    this.status("帧索引就绪");
    this.update(this.time);
    return index;
  }
  destroy() {
    this.alive = false;
    for (const c of this.requests.values()) c.abort();
    for (const c of this.cache.values())
      for (const f of c.values()) URL.revokeObjectURL(f.url);
    this.cache.clear();
  }
  update(time, prefetch = false, exact = null) {
    this.time = time;
    this.prefetch = prefetch;
    this.exact = exact;
    if (!this.alive || !this.index) return;
    for (const cam of Object.keys(this.index.cameras)) this.paint(cam);
  }
  targetIndex(cam) {
    const times = this.index.cameras[cam].times_s;
    return this.exact?.cam === cam &&
      Number.isInteger(this.exact.index) &&
      times[this.exact.index] === this.time
      ? this.exact.index
      : nearestFrame(times, this.time);
  }
  paint(cam) {
    if (!this.alive) return;
    const img = this.root.querySelector(`img[data-camera="${cam}"]`);
    if (!img) return;
    const times = this.index.cameras[cam].times_s,
      i = this.targetIndex(cam),
      card = img.parentElement;
    if (i < 0 || Math.abs(times[i] - this.time) > 0.15) {
      card.classList.add("frame-unavailable");
      card.querySelector(".camera-error").textContent = "此时刻无图像";
      card.querySelector(".camera-error").hidden = false;
      return;
    }
    card.classList.remove("frame-unavailable");
    const cached = this.cache.get(cam)?.get(i);
    if (cached) {
      if (this.last.get(cam) !== i && !this.displayBusy.has(cam)) {
        this.last.set(cam, i);
        if (cached.size) {
          this.displayBusy.add(cam);
          img.onload = () => {
            this.displayBusy.delete(cam);
            if (!this.alive || this.last.get(cam) !== i) return;
            card.querySelector(".camera-error").hidden = true;
            img.dataset.frameIndex = String(i);
            img.dataset.frameTime = String(times[i]);
            img.dataset.paintCount = String(
              Number(img.dataset.paintCount || 0) + 1,
            );
            card.querySelector(".camera-frame").textContent =
              `${i + 1} / ${times.length}`;
            this.onPainted(cam, i);
            queueMicrotask(() => {
              if (this.alive) this.paint(cam);
            });
          };
          img.onerror = () => {
            this.displayBusy.delete(cam);
            if (!this.alive) return;
            card.querySelector(".camera-error").textContent = "图像解码失败";
            card.querySelector(".camera-error").hidden = false;
            queueMicrotask(() => {
              if (this.alive) this.paint(cam);
            });
          };
          img.src = cached.url;
        } else {
          card.querySelector(".camera-error").textContent = "此帧无法读取";
          card.querySelector(".camera-error").hidden = false;
        }
      }
      if (this.prefetch) {
        const next = Math.floor(i / 8) * 8 + 8;
        if (next < times.length && !this.cache.get(cam)?.has(next))
          this.request(cam, next);
      }
    } else this.request(cam, Math.floor(i / 8) * 8);
  }
  async request(cam, start) {
    if (this.busy.has(cam) || this.failed.has(cam) || !this.alive) return;
    const controller = new AbortController();
    this.busy.set(cam, start);
    this.requests.set(cam, controller);
    let succeeded = false;
    try {
      const url = `/api/frame-batch?ep=${this.ep}&cam=${cam}&start=${start}&count=8&token=${encodeURIComponent(this.index.token)}`;
      const res = await fetch(url, { signal: controller.signal });
      if (!res.ok) throw Error((await res.json()).error || "图像读取失败");
      const batch = parseFrameBatch(await res.arrayBuffer());
      if (!this.alive) return;
      if (batch.token !== this.index.token)
        throw Error("源文件已变化，请重新载入");
      if (!this.cache.has(cam)) this.cache.set(cam, new Map());
      const cache = this.cache.get(cam);
      for (const frame of batch.frames) {
        const old = cache.get(frame.index);
        if (old) URL.revokeObjectURL(old.url);
        cache.set(frame.index, {
          url: URL.createObjectURL(frame.blob),
          size: frame.size,
        });
      }
      const wanted = this.targetIndex(cam);
      while (cache.size > 48) {
        const far = [...cache.keys()]
          .filter((i) => i !== this.last.get(cam))
          .sort((a, b) => Math.abs(b - wanted) - Math.abs(a - wanted))[0];
        if (far === undefined) break;
        URL.revokeObjectURL(cache.get(far).url);
        cache.delete(far);
      }
      succeeded = true;
    } catch (e) {
      if (e.name !== "AbortError" && this.alive) {
        this.failed.add(cam);
        this.status(e.message, true);
      }
    } finally {
      this.busy.delete(cam);
      this.requests.delete(cam);
      if (succeeded && this.alive) this.paint(cam);
    }
  }
}
