// A queued RAF timestamp can precede a click handler's performance.now().
export function advancePlayback(time, now, last, speed, duration) {
  const elapsed = Math.max(0, Math.min(0.1, (now - last) / 1000));
  return Math.max(0, Math.min(duration, time + elapsed * speed));
}
