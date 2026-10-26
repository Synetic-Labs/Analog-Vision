// analog-vision on the GPU: a picture sent as NTSC composite video over a 5.8 GHz FM link and
// decoded again, signal by signal, in WebGL2, fast enough to watch live. A port of the Python
// package beside it, stage for stage; read the module each stage names for the physics.
// Nothing is painted on: grain, colour noise, sparklies, torn lines, the colour killer,
// rolling, echoes' rainbows and snow all come out of the chain. tests/test_web.py holds it to
// the Python.
//
// The signal is held as rows of one line each, in rings of a frame (525 lines): composite at
// 4fsc (910 samples a line), the radio at 8fsc (1820). Each step encodes the lines due, from
// the latest picture, and runs them through:
//
//   raster (encode)          the camera's picture to 754 x 480, as PIL's Lanczos scales it
//   encode (ntsc, encode)    picture and OSD to composite: sync, burst, band-limited Y'UV
//   freq, rx, if, disc (fm)  frequency modulation, echoes, thermal noise, tuning offset, IF
//                            filter, discriminator
//   video (fm)               the receiver's video filter and clipping
//   filt ... summ (decode)   the decoder's streams: sync, luma, chroma, the comb's, vertical
//                            integrator, sync edges and level measurements at every sample
//   lines (decode)           the decoder itself, line by line: flywheel, vertical sync, clamp,
//                            AGC, burst and colour killer. Sequential, so each of its
//                            fragments runs it from the last step's state to its own line.
//   picture (decode)         each decoded line into its field, Y'UV
//   frame (pipeline)         the last two whole fields woven (or the last line-doubled), as
//                            R'G'B', 754 x 480; then the recorder (pipeline.Dvr), if any
//
// Settings are the Python's, by the same names: `link` (fm.Link), `decoder`
// (decode.Decoder), `deinterlace` and `dvr` (pipeline).
//
// An OSD can go in as a flight controller's OSD chip puts it: its pixels switch the video to
// white or black, after the camera and before the transmitter, so the link spoils it too.

const FSC = 315e6 / 88;
const FS = 4 * FSC;
const FS_RF = 2 * FS;
const LINE = 910;
const HALF = 455;
const LINES = 525;
const LINE_RATE = FS / LINE;
const ACTIVE = 754;
const ACTIVE_LINES = 480;
/** Lines the decoder gets through in one step at most: the lines pass's fragments. */
const MAX_LINES = 320;
/** Lines encoded in one step at most: after a stall, the rest is skipped. */
const MAX_BATCH = 300;
const BLOCK = 14;
const KAISER_BETA = 6;
/** Echoes the link carries at most. */
export const MAX_ECHOES = 8;
/** The longest echo, s: longer ones are cut to it. */
const MAX_ECHO_DELAY_S = 1.2e-6;
/** Fields kept: the one being drawn and the two before it. */
const LAYERS = 3;

/** The Python's defaults (fm.Link, decode.Decoder, pipeline.AnalogVideo and Dvr). */
export const DEFAULTS = Object.freeze({
  link: Object.freeze({
    cnr_db: 30,
    deviation_hz: 5e6,
    if_bandwidth_hz: 18e6,
    video_bandwidth_hz: 5e6,
    carrier_offset_hz: 0,
    multipath: Object.freeze([]),
  }),
  decoder: Object.freeze({
    sync_bandwidth_hz: 1.5e6,
    sync_slice_ire: -20,
    h_window: 40,
    h_phase_gain: 0.3,
    h_freq_gain: 0.01,
    h_search_after: 8,
    v_accept_after: 230,
    v_free_lines: 272,
    yc: "notch",
    luma_bandwidth_hz: 4.2e6,
    chroma_bandwidth_hz: 1.3e6,
    chroma_lowpass_hz: 0.6e6,
    burst_smoothing: 0.1,
    lock_smoothing: 0.02,
    killer_off: 0.25,
    killer_on: 0.35,
    killer_snr_off: 2.2,
    killer_snr_on: 2.5,
    acc_max_gain: 4,
    clamp_smoothing: 0.5,
    agc_smoothing: 0.05,
    agc_range: Object.freeze([0.25, 4]),
    h_lock_smoothing: 0.05,
    lost_below: 0.5,
    on_loss: "snow",
  }),
  deinterlace: "weave",
  dvr: null,
});

/** A goggles' recorder (pipeline.Dvr): one field, 640 x 480, JPEG at 50. */
export const DVR = Object.freeze({ quality: 50, one_field: true, size: Object.freeze([640, 480]) });
/** A monitor's HDMI into a capture card (Dvr.hdmi_capture). */
export const HDMI_CAPTURE = Object.freeze({ quality: 90, one_field: false, size: Object.freeze([960, 720]) });

// -- link budget (fm.link_cnr_db, fm.indoor_echoes) -----------------------------------------

/** CNR at the receiver, dB, over free space: received power over thermal noise (-174 dBm/Hz)
 * in the IF bandwidth, raised by the noise figure. With the defaults the RTC6715's -85 dBm
 * sensitivity is about 10 dB. */
export function linkCnrDb(distanceM, txMw = 25, txGainDbi = 2, rxGainDbi = 2, more = {}) {
  const {
    frequency_hz = 5.8e9,
    noise_figure_db = 6,
    if_bandwidth_hz = DEFAULTS.link.if_bandwidth_hz,
    extra_loss_db = 0,
  } = more;
  const fspl = 20 * Math.log10((4 * Math.PI * Math.max(distanceM, 0.1) * frequency_hz) / 299_792_458);
  const rx = 10 * Math.log10(txMw) + txGainDbi + rxGainDbi - fspl - extra_loss_db;
  const noise = -174 + 10 * Math.log10(if_bandwidth_hz) + noise_figure_db;
  return rx - noise;
}

/** A random indoor channel (fm.indoor_echoes): `count` echoes, power falling off
 * exponentially with delay, together `k_db` below the direct path, each turning at its own
 * Doppler difference at `speed_ms`. `random` gives numbers in [0, 1). */
export function indoorEchoes(random, { delay_spread_s = 30e-9, k_db = 3, speed_ms = 3, count = 6, frequency_hz = 5.8e9 } = {}) {
  const delays = Array.from({ length: count }, () => -delay_spread_s * Math.log(1 - random()))
    .sort((a, b) => a - b)
    .map((d) => d + 3e-9);
  const power = delays.map((d) => Math.exp(-d / delay_spread_s));
  const total = power.reduce((a, b) => a + b, 0);
  const perMs = frequency_hz / 299_792_458;
  const direct = Math.cos(random() * 2 * Math.PI);
  return delays.map((d, i) => ({
    delay_s: d,
    level_db: 10 * Math.log10((power[i] * 10 ** (-k_db / 10)) / total),
    phase_deg: random() * 360,
    doppler_hz: speed_ms * perMs * (Math.cos(random() * 2 * Math.PI) - direct),
  }));
}

// -- filters (dsp) --------------------------------------------------------------------------

function besselI0(x) {
  let sum = 1;
  let term = 1;
  for (let k = 1; k < 50; k++) {
    term *= (x / (2 * k)) ** 2;
    sum += term;
  }
  return sum;
}

function kaiser(n) {
  return Array.from({ length: n }, (_, i) => {
    const r = (2 * i) / (n - 1) - 1;
    return besselI0(KAISER_BETA * Math.sqrt(1 - r * r)) / besselI0(KAISER_BETA);
  });
}

const sinc = (x) => (x === 0 ? 1 : Math.sin(Math.PI * x) / (Math.PI * x));

/** scipy.signal.firwin(taps, cutoff, fs=fs, window=("kaiser", 6)): unity at DC. */
function lowpass(taps, cutoffHz, fs) {
  const c = Math.min(cutoffHz / (fs / 2), 1);
  const w = kaiser(taps);
  const mid = (taps - 1) / 2;
  const h = w.map((wi, i) => c * sinc(c * (i - mid)) * wi);
  const sum = h.reduce((a, b) => a + b, 0);
  return h.map((x) => x / sum);
}

/** firwin(taps, [low, high], pass_zero=False): unity at the band's centre. */
function bandpass(taps, lowHz, highHz, fs) {
  const c1 = Math.max(lowHz / (fs / 2), 0);
  const c2 = Math.min(highHz / (fs / 2), 1);
  const w = kaiser(taps);
  const mid = (taps - 1) / 2;
  const h = w.map((wi, i) => (c2 * sinc(c2 * (i - mid)) - c1 * sinc(c1 * (i - mid))) * wi);
  const centre = (c1 + c2) / 2;
  const gain = h.reduce((a, x, i) => a + x * Math.cos(Math.PI * centre * (i - mid)), 0);
  return h.map((x) => x / gain);
}

/** A raised-cosine pulse of `taps`, summing to 1 (dsp.smoothing). */
function smoothing(taps) {
  const m = taps + 2;
  const w = Array.from({ length: m }, (_, i) => 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (m - 1))).slice(1, -1);
  const sum = w.reduce((a, b) => a + b, 0);
  return w.map((x) => x / sum);
}

function convolve(a, b) {
  const out = new Array(a.length + b.length - 1).fill(0);
  a.forEach((x, i) => b.forEach((y, j) => (out[i + j] += x * y)));
  return out;
}

/** The decoder's filters, run one after another, as single kernels on its input (decode.py's
 * delays: sync 20, bp 20, luma 15, demod 30, burst demod 20, the comb's edge 30). */
function decoderKernels(d) {
  const bp = bandpass(41, FSC - d.chroma_bandwidth_hz, FSC + d.chroma_bandwidth_hz, FS);
  // Luma: the input delayed to match the band-pass, less it (a notch), low-passed. Kept as
  // the low-pass alone and the low-passed band-pass, which the comb needs on its own.
  const luma = lowpass(31, d.luma_bandwidth_hz, FS);
  // Chroma: band-pass, to baseband against the free-running subcarrier, low-passed. Mixing by
  // 2(-i)^n between the two moves to the front as 2(-i)^n and i^j on the low-pass's taps.
  const chroma = (lp) => {
    const re = new Array(lp.length + bp.length - 1).fill(0);
    const im = new Array(re.length).fill(0);
    lp.forEach((l, j) => {
      const [cr, ci] = [
        [1, 0],
        [0, 1],
        [-1, 0],
        [0, -1],
      ][j % 4];
      bp.forEach((b, i) => {
        re[i + j] += l * b * cr;
        im[i + j] += l * b * ci;
      });
    });
    return [re, im];
  };
  const [zr, zi] = chroma(lowpass(61, d.chroma_lowpass_hz, FS));
  const [br, bi] = chroma(lowpass(41, d.chroma_bandwidth_hz, FS));
  return {
    sync: lowpass(41, d.sync_bandwidth_hz, FS),
    luma,
    lumaBp: convolve(luma, bp),
    zr,
    zi,
    br,
    bi,
    edge: lowpass(61, 1.0e6, FS),
  };
}

// -- shaders --------------------------------------------------------------------------------

const HEADER = `#version 300 es
precision highp float;
precision highp int;
precision highp sampler2D;
const int LINE = 910;
const int LINES = 525;
const int FRAME = 477750;
const int RLINE = 1820;
const int RFRAME = 955500;
const int BLOCK = ${BLOCK};
const int BLOCKS = FRAME / BLOCK;
const int BLOCKS_LINE = LINE / BLOCK;
const float PI = 3.14159265358979;
const float SYNC = -40.0;
const float SETUP = 7.5;
const float SPAN = 92.5;
const float BURST = 20.0;
const float MID = 30.0;
const int HSYNC = 67;
const int EQUALIZING = 33;
const int BROAD = 388;
uniform sampler2D uTaps;
uniform int uL0;
int wrapN(int n) { n %= FRAME; return n < 0 ? n + FRAME : n; }
ivec2 at(int n) { n = wrapN(n); return ivec2(n % LINE, n / LINE); }
ivec2 atRF(int m) { m %= RFRAME; if (m < 0) m += RFRAME; return ivec2(m % RLINE, m / RLINE); }
float tap(int row, int j) { return texelFetch(uTaps, ivec2(j, row), 0).r; }
int ringRow() { return int(gl_FragCoord.y); }
/** The line this row holds now, counted from the start. */
int absLine() { int r0 = uL0 % LINES; return uL0 + (ringRow() - r0 + LINES) % LINES; }
int here() { return ringRow() * LINE + int(gl_FragCoord.x); }
int hereRF() { return ringRow() * RLINE + int(gl_FragCoord.x); }
vec2 cmul(vec2 a, vec2 b) { return vec2(a.x * b.x - a.y * b.y, a.x * b.y + a.y * b.x); }
vec2 cis(float a) { return vec2(cos(a), sin(a)); }
/** (-i)^k */
vec2 negI(int k) { k &= 3; return k == 0 ? vec2(1, 0) : k == 1 ? vec2(0, -1) : k == 2 ? vec2(-1, 0) : vec2(0, 1); }
/** The sync pulse starting half line h (0 to 1049) of the frame (ntsc.half_line). */
int pulse(int h) {
  for (int s = 0; s < 2; s++) {
    int k = h - s * 525;
    if ((k >= 0 && k < 6) || (k >= 12 && k < 18)) return EQUALIZING;
    if (k >= 6 && k < 12) return BROAD;
  }
  return h % 2 == 0 ? HSYNC : 0;
}
/** Line 1 to 525 starts with an ordinary sync, and so carries a burst. */
bool hasBurst(int line) { return pulse(2 * (line - 1)) == HSYNC; }
`;

const QUAD_VS = `#version 300 es
void main() {
  int v = gl_VertexID;
  gl_Position = vec4(v == 1 || v == 4 || v == 5 ? 1.0 : -1.0, v == 2 || v == 3 || v == 5 ? 1.0 : -1.0, 0.0, 1.0);
}`;

const TAP = {
  encY: 0, encC: 1, up: 2, if: 3, video: 4, sync: 5, luma: 6, lumaBp: 7,
  zr: 8, zi: 9, br: 10, bi: 11, burst: 12, edge: 13,
}; // prettier-ignore

/** PIL's Lanczos (support 3, widened by the scale when shrinking), one axis of the camera's
 * picture at a time: `uAxis` 0 across, then 1 down, to 754 x 480 (encode.raster). */
const RASTER_FS = `${HEADER}
uniform sampler2D uSrc;
uniform int uAxis;
uniform int uIn;
out vec4 o;
float sincf(float x) { if (x == 0.0) return 1.0; x *= PI; return sin(x) / x; }
float lanczos(float x) { return x >= -3.0 && x < 3.0 ? sincf(x) * sincf(x / 3.0) : 0.0; }
void main() {
  ivec2 p = ivec2(gl_FragCoord.xy);
  int out_ = uAxis == 0 ? ${ACTIVE} : ${ACTIVE_LINES};
  int i = uAxis == 0 ? p.x : p.y;
  float scale = float(uIn) / float(out_);
  float fscale = max(scale, 1.0);
  float support = 3.0 * fscale;
  float centre = (float(i) + 0.5) * scale;
  int lo = max(int(centre - support + 0.5), 0);
  int hi = min(int(centre + support + 0.5), uIn);
  vec3 sum = vec3(0);
  float ww = 0.0;
  for (int k = lo; k < hi; k++) {
    float w = lanczos((float(k) - centre + 0.5) / fscale);
    sum += w * texelFetch(uSrc, uAxis == 0 ? ivec2(k, p.y) : ivec2(p.x, k), 0).rgb;
    ww += w;
  }
  vec3 c = sum / ww;
  o = vec4(uAxis == 0 ? c : clamp(c, 0.0, 1.0), 1);
}`;

/** encode.py: one sample of composite, IRE. */
const ENCODE_FS = `${HEADER}
uniform sampler2D uRaster;
uniform sampler2D uOsd;
uniform ivec3 uOsdSize; // width, height, top line in the field; width 0: no OSD
out float o;
float syncAt(int n) {
  n = wrapN(n);
  int c = n % LINE;
  int half_ = c >= 455 ? 1 : 0;
  return c - 455 * half_ < pulse(2 * (n / LINE) + half_) ? SYNC : 0.0;
}
void main() {
  int c = int(gl_FragCoord.x);
  int line = ringRow() + 1;
  int n = here();
  float x = 0.25 * syncAt(n - 1) + 0.5 * syncAt(n) + 0.25 * syncAt(n + 1);
  int k = ((absLine() & 1) * 2 + c) & 3;
  float s = k == 1 ? 1.0 : k == 3 ? -1.0 : 0.0;
  float co = k == 0 ? 1.0 : k == 2 ? -1.0 : 0.0;
  int j = c - 76;
  if (hasBurst(line) && j >= 0 && j < 36) x -= BURST * tap(${TAP.burst}, j) * s;
  int f = -1;
  int row = -1;
  if (line >= 23 && line < 263) { f = line - 23; row = 2 * f + 1; }
  else if (line >= 286) { f = line - 286; row = 2 * f; }
  int a = c - 135;
  if (row >= 0 && a >= 0 && a < ${ACTIVE}) {
    float y = 0.0;
    vec3 rgb = vec3(0);
    for (int i = -20; i <= 20; i++) {
      vec3 p = texelFetch(uRaster, ivec2(clamp(a + i, 0, ${ACTIVE - 1}), row), 0).rgb;
      if (i >= -15 && i <= 15) y += tap(${TAP.encY}, i + 15) * dot(p, vec3(0.299, 0.587, 0.114));
      rgb += tap(${TAP.encC}, i + 20) * p;
    }
    float yc = dot(rgb, vec3(0.299, 0.587, 0.114));
    float u = 0.492111 * (rgb.b - yc);
    float v = 0.877283 * (rgb.r - yc);
    float video = SETUP + SPAN * (y + u * s + v * co);
    int oy = f - uOsdSize.z;
    if (uOsdSize.x > 0 && oy >= 0 && oy < uOsdSize.y) {
      // The OSD chip's pixels, white or black, in place of the video; edges as the chip's.
      float add = 0.0;
      for (int i = -1; i <= 1; i++) {
        int ox = clamp((a + i) * uOsdSize.x / ${ACTIVE}, 0, uOsdSize.x - 1);
        vec4 g = texelFetch(uOsd, ivec2(ox, oy), 0);
        if (g.a > 0.5) add += (i == 0 ? 0.5 : 0.25) * (SETUP + SPAN * g.r - video);
      }
      video += add;
    }
    float env = a == 0 || a == ${ACTIVE - 1} ? 0.25 : a == 1 || a == ${ACTIVE - 2} ? 0.75 : 1.0;
    x += video * env;
  }
  o = x;
}`;

/** fm.py, the transmitter: up to 8fsc, then the frequency, radians a sample. */
const FREQ_FS = `${HEADER}
uniform sampler2D uComp;
uniform float uRadPerIre;
out float o;
void main() {
  int m = hereRF();
  float video = 0.0;
  for (int j = m & 1; j < 63; j += 2) {
    int q = m - j;
    if (q < 0) q += RFRAME;
    video += tap(${TAP.up}, j) * texelFetch(uComp, at(q / 2), 0).r;
  }
  o = (video - MID) * uRadPerIre;
}`;

/** fm.py, the air: the received signal against the transmitted carrier's phase, 1 plus the
 * echoes and the noise; and the frequency the receiver sees, the tuning offset added. Each
 * echo is the carrier's phase \`delay\` samples back (interpolated, as np.interp does it),
 * turned by its phase and Doppler. uEcho: level, delay in samples, turn at line uL0's first
 * sample, turn a sample. */
const RX_FS = `${HEADER}
uniform sampler2D uFreq;
uniform float uSigma;
uniform uint uSeed;
uniform float uOffset;
uniform int uEchoes;
uniform vec4 uEcho[${MAX_ECHOES}];
layout(location = 0) out float oFreq;
layout(location = 1) out vec2 oRx;
uvec3 pcg3d(uvec3 v) {
  v = v * 1664525u + 1013904223u;
  v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
  v ^= v >> 16u;
  v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
  return v;
}
void main() {
  int m = hereRF();
  vec2 rx = vec2(1, 0);
  float since = float((absLine() - uL0) * RLINE + int(gl_FragCoord.x));
  for (int e = 0; e < uEchoes; e++) {
    vec4 echo = uEcho[e];
    int whole = int(floor(echo.y));
    float back = (echo.y - float(whole)) * texelFetch(uFreq, atRF(m - whole), 0).r;
    for (int j = 0; j < whole; j++) back += texelFetch(uFreq, atRF(m - j), 0).r;
    rx += echo.x * cis(echo.z + echo.w * since - back);
  }
  // The noise, white, circular: turned to the carrier's phase it is still white.
  uvec3 h = pcg3d(uvec3(uint(absLine()), uint(gl_FragCoord.x), uSeed));
  float u1 = (float(h.x >> 8u) + 0.5) / 16777216.0;
  float u2 = float(h.y >> 8u) / 16777216.0;
  oRx = rx + uSigma * sqrt(-2.0 * log(u1)) * cis(2.0 * PI * u2);
  oFreq = texelFetch(uFreq, atRF(m), 0).r + uOffset;
}`;

/** fm.py, the receiver's IF filter, against the carrier's phase at its centre tap: only the
 * phase's local changes are needed, so no running phase is kept. */
const IF_FS = `${HEADER}
uniform sampler2D uFreq;
uniform sampler2D uRx;
out vec2 o;
void main() {
  int k = hereRF();
  vec2 b = tap(${TAP.if}, 31) * texelFetch(uRx, atRF(k - 31), 0).rg;
  float psi = 0.0;
  for (int j = 30; j >= 0; j--) {
    psi += texelFetch(uFreq, atRF(k - j), 0).r;
    b += tap(${TAP.if}, j) * cmul(cis(psi), texelFetch(uRx, atRF(k - j), 0).rg);
  }
  psi = 0.0;
  for (int j = 32; j < 63; j++) {
    psi -= texelFetch(uFreq, atRF(k - j + 1), 0).r;
    b += tap(${TAP.if}, j) * cmul(cis(psi), texelFetch(uRx, atRF(k - j), 0).rg);
  }
  o = b;
}`;

/** fm.py, the discriminator: the phase step from each sample to the next, as video, IRE. */
const DISC_FS = `${HEADER}
uniform sampler2D uIf;
uniform sampler2D uFreq;
uniform float uRadPerIre;
out float o;
void main() {
  int k = hereRF();
  vec2 b = texelFetch(uIf, atRF(k), 0).rg;
  vec2 a = texelFetch(uIf, atRF(k - 1), 0).rg;
  vec2 step_ = cmul(cmul(b, vec2(a.x, -a.y)), cis(texelFetch(uFreq, atRF(k - 31), 0).r));
  o = atan(step_.y, step_.x) / uRadPerIre + MID;
}`;

/** fm.py, the receiver's video amplifier: filtered, back to 4fsc, clipped. */
const VIDEO_FS = `${HEADER}
uniform sampler2D uDisc;
out float o;
void main() {
  int m = 2 * here();
  float v = 0.0;
  for (int j = 0; j < 63; j++) v += tap(${TAP.video}, j) * texelFetch(uDisc, atRF(m - j), 0).r;
  o = clamp(v, -60.0, 140.0);
}`;

/** decode.py's streams from the video: sync (low-passed), luma (notch), chroma and burst
 * chroma at baseband; for the comb, the low-passed chroma band (its luma is the notch's plus
 * that band from this line and the last) and the edge detector's low-pass. */
const FILT_FS = `${HEADER}
uniform sampler2D uVideo;
layout(location = 0) out vec2 oSyncY;
layout(location = 1) out vec4 oChroma;
layout(location = 2) out vec2 oComb;
void main() {
  int n = here();
  float sync = 0.0, low = 0.0, band = 0.0, edge = 0.0;
  vec2 z = vec2(0), zb = vec2(0);
  for (int m = 0; m < 101; m++) {
    float x = texelFetch(uVideo, at(n - m), 0).r;
    if (m < 41) sync += tap(${TAP.sync}, m) * x;
    if (m >= 20 && m < 51) low += tap(${TAP.luma}, m - 20) * x;
    if (m < 71) band += tap(${TAP.lumaBp}, m) * x;
    if (m < 61) edge += tap(${TAP.edge}, m) * x;
    z += x * vec2(tap(${TAP.zr}, m), tap(${TAP.zi}, m));
    if (m < 81) zb += x * vec2(tap(${TAP.br}, m), tap(${TAP.bi}, m));
  }
  vec2 turn = 2.0 * negI((absLine() & 1) * 2 + int(gl_FragCoord.x) + 400 - 20);
  oSyncY = vec2(sync, low - band);
  oChroma = vec4(cmul(turn, z), cmul(turn, zb));
  oComb = vec2(band, edge);
}`;

/** The vertical integrator (351 samples), in two steps: 27, then 13 of those. */
const SLICE_FS = `${HEADER}
uniform sampler2D uSyncY;
uniform float uSlice;
out float o;
void main() {
  int n = here();
  float a = 0.0;
  for (int j = 0; j < 27; j++) a += texelFetch(uSyncY, at(n - j), 0).r < uSlice ? 1.0 : 0.0;
  o = a;
}`;

const VINT_FS = `${HEADER}
uniform sampler2D uSlice;
out float o;
void main() {
  int n = here();
  float a = 0.0;
  for (int q = 0; q < 13; q++) a += texelFetch(uSlice, at(n - 27 * q), 0).r;
  o = a / 351.0;
}`;

/** At every sample, what the decoder would measure from there: a sync edge (decode
 * _crossings: falling through the slice, and staying down 2.5 us; where between this sample
 * and the next, or -1), and the means for the back porch, sync tip and burst. */
const MEAS_FS = `${HEADER}
uniform sampler2D uSyncY;
uniform sampler2D uChroma;
uniform float uSlice;
layout(location = 0) out float oEdge;
layout(location = 1) out vec4 oMeas;
void main() {
  int n = here();
  float s0 = texelFetch(uSyncY, at(n), 0).r;
  float s1 = texelFetch(uSyncY, at(n + 1), 0).r;
  float edge = -1.0;
  if (s0 >= uSlice && s1 < uSlice) {
    float down = 0.0;
    for (int i = 6; i < 41; i++) down += texelFetch(uSyncY, at(n + i), 0).r;
    if (down / 35.0 < uSlice) edge = (s0 - uSlice) / (s0 - s1);
  }
  oEdge = edge;
  float porch = 0.0, tip = 0.0;
  for (int i = 0; i < 51; i++) {
    float y = texelFetch(uSyncY, at(n + i), 0).g;
    tip += y;
    if (i < 15) porch += y;
  }
  vec2 burst = vec2(0);
  for (int i = 0; i < 20; i++) burst += texelFetch(uChroma, at(n + i), 0).ba;
  oMeas = vec4(porch / 15.0, tip / 51.0, burst / 20.0);
}`;

/** Each block of samples: its first and last sync edge (offset in the block, with the
 * fraction) and the first sample past the vertical integrator's threshold; -1 for none. */
const SUMM_FS = `${HEADER}
uniform sampler2D uEdge;
uniform sampler2D uV;
out vec4 o;
void main() {
  int n0 = ringRow() * LINE + int(gl_FragCoord.x) * BLOCK;
  vec4 s = vec4(-1);
  for (int i = 0; i < BLOCK; i++) {
    float e = texelFetch(uEdge, at(n0 + i), 0).r;
    if (e >= 0.0) {
      if (s.x < 0.0) s.x = float(i) + e;
      s.y = float(i) + e;
    }
    if (s.z < 0.0 && texelFetch(uV, at(n0 + i), 0).r > 0.6) s.z = float(i);
  }
  o = s;
}`;

/** decode.VideoDecoder, line by line. State, as each line is drawn:
 *   s0: where its sync is (whole sample in the ring, fraction), line period, lines missed
 *   s1: horizontal lock, line number, lines since the vertical retrace, field parity (0 none)
 *   s2: clamp, AGC (-1 none yet), colour reference (the burst, complex)
 *   s3: lock detector, burst noise, colour flags (on, ok, good), 1 if valid
 *   s4: this field's lines with a sync and lines in colour, fields begun, the last two whole
 *       fields' parities (last + 4 prev)
 *   s5: the last two whole fields' shares of lines with a sync and in colour */
const STATE_DECL = `
int pI; float pF; float period; int missed;
float hLock; int lineNo; int since; int parity;
float clampL; float agc; vec2 burst;
float lock; float burstNoise; bool colour, colourOk, colourGood;
int syncedLines; int colourLines; int fields; int lastParity; int prevParity;
float lastSynced, lastColour, prevSynced, prevColour;
void readState(vec4 s0, vec4 s1, vec4 s2, vec4 s3, vec4 s4, vec4 s5) {
  pI = int(s0.x); pF = s0.y; period = s0.z; missed = int(s0.w);
  hLock = s1.x; lineNo = int(s1.y); since = int(s1.z); parity = int(s1.w);
  clampL = s2.x; agc = s2.y; burst = s2.zw;
  lock = s3.x; burstNoise = s3.y;
  int flags = int(s3.z);
  colour = (flags & 1) != 0; colourOk = (flags & 2) != 0; colourGood = (flags & 4) != 0;
  syncedLines = int(s4.x); colourLines = int(s4.y); fields = int(s4.z);
  lastParity = int(s4.w) & 3; prevParity = int(s4.w) >> 2;
  lastSynced = s5.x; lastColour = s5.y; prevSynced = s5.z; prevColour = s5.w;
}`;

const LINES_FS = `${HEADER}
uniform sampler2D uS0, uS1, uS2, uS3, uS4, uS5;
uniform sampler2D uEdge, uSumm, uMeas, uV;
uniform int uEnd;
uniform int uHWindow, uSearchAfter, uVAccept, uVFree;
uniform float uPhaseGain, uFreqGain, uClampS, uAgcS, uBurstS, uLockS, uHLockS;
uniform vec2 uAgcRange;
uniform vec4 uKiller; // off, on, snr off, snr on
layout(location = 0) out vec4 o0;
layout(location = 1) out vec4 o1;
layout(location = 2) out vec4 o2;
layout(location = 3) out vec4 o3;
layout(location = 4) out vec4 o4;
layout(location = 5) out vec4 o5;
const int DELAY_SYNC = 20, DELAY_Y = 35, DELAY_ZB = 40, DELAY_V = 195;
const int MARGIN = LINE + LINE + DELAY_V + 2;
/** Where the decoder first looks for a sync (decode _acquire: half a line in). */
const int ACQUIRE = 455 - 20;
${STATE_DECL}

vec4 summ(int blk) { blk %= BLOCKS; if (blk < 0) blk += BLOCKS; return texelFetch(uSumm, ivec2(blk % BLOCKS_LINE, blk / BLOCKS_LINE), 0); }
vec4 measAt(int i, float f) { return mix(texelFetch(uMeas, at(i), 0), texelFetch(uMeas, at(i + 1), 0), f); }
void advance(float d) { float t = pF + d; float fl = floor(t); pI = wrapN(pI + int(fl)); pF = t - fl; }

/** The edge nearest to p + period within the window (decode _next_sync), as an offset from
 * it in samples; or 1e9 for none. Local coordinates: 0 is the expected sync's sample in the
 * edge stream; candidates from -w to w - 1. */
float nearestEdge(int base, float ef, int w) {
  int bs = -(base % BLOCK);
  int blk = (base - base % BLOCK) / BLOCK;
  float best = 1e9;
  for (int i = 0; i < BLOCK; i++) {
    int s = bs + i;
    if (s < -w || s >= w) continue;
    float e = texelFetch(uEdge, at(base + s), 0).r;
    if (e >= 0.0 && abs(float(s) + e - ef) < abs(best)) best = float(s) + e - ef;
  }
  for (int q = 1; q <= 80; q++) {
    int start = bs + BLOCK * q;
    if (start >= w || float(start) - ef >= abs(best)) break;
    float first = summ(blk + q).x;
    if (first >= 0.0) {
      if (start + int(first) < w && float(start) + first - ef < abs(best)) best = float(start) + first - ef;
      break;
    }
  }
  for (int q = 1; q <= 80; q++) {
    int start = bs - BLOCK * q;
    if (start + BLOCK <= -w || ef - float(start + BLOCK) >= abs(best)) break;
    float last = summ(blk - q).y;
    if (last >= 0.0) {
      if (start + int(last) >= -w && ef - float(start) - last < abs(best)) best = float(start) + last - ef;
      break;
    }
  }
  return best;
}

void nextSync() {
  float expect = period;
  int w = missed >= uSearchAfter ? 455 + uHWindow : uHWindow;
  // The expected sync, in the edge stream.
  float t = pF + expect;
  int base = wrapN(pI + int(floor(t)) + DELAY_SYNC);
  float ef = fract(t);
  float err = nearestEdge(base, ef, w);
  if (err > 1e8) {
    missed++;
    advance(expect);
    return;
  }
  missed = 0;
  syncedLines++;
  if (w > uHWindow) { advance(expect + err); return; }
  period = clamp(period + uFreqGain * err, 890.0, 930.0);
  advance(expect + uPhaseGain * err);
}

/** The first whole sample from the line's sync, in its first line, where the vertical
 * integrator is past its threshold; -1 for none. */
int vFirst(int base) {
  int bs = -(base % BLOCK);
  int blk = (base - base % BLOCK) / BLOCK;
  for (int i = 0; i < BLOCK + bs; i++)
    if (texelFetch(uV, at(base + i), 0).r > 0.6) return i;
  for (int q = 1; bs + BLOCK * q < LINE; q++) {
    float first = summ(blk + q).z;
    if (first >= 0.0) return bs + BLOCK * q + int(first);
  }
  return -1;
}

/** Where in this line the vertical integrator, read between samples as the decoder reads
 * it, first passes its threshold; -1 for none. */
int vsyncHit() {
  int base = wrapN(pI + DELAY_V);
  int k = vFirst(base);
  if (k < 0) return -1;
  for (int j = max(k - 1, 0); j < min(k + 3, LINE); j++) {
    float v = mix(texelFetch(uV, at(base + j), 0).r, texelFetch(uV, at(base + j + 1), 0).r, pF);
    if (v > 0.6) return j;
  }
  return k;
}

void retrace(int p) {
  if (parity != 0) {
    // The field so far is done (decode _finish).
    prevParity = lastParity; prevSynced = lastSynced; prevColour = lastColour;
    lastParity = parity;
    lastSynced = min(float(syncedLines) / float(max(since, 1)), 1.0);
    lastColour = min(float(colourLines) / 240.0, 1.0);
  }
  colour = colourGood || (colour && colourOk);
  parity = p;
  lineNo = p == 1 ? 4 : 266;
  since = 0;
  syncedLines = 0;
  colourLines = 0;
  fields++;
}

void decodeLine() {
  int hit = since >= uVAccept ? vsyncHit() : -1;
  if (hit >= 0) retrace(hit < 455 ? 1 : 2);
  else if (since >= uVFree) retrace(parity == 1 ? 2 : 1);
  int frameLine = ((lineNo - 1) % LINES + LINES) % LINES + 1;
  bool ordinary = hasBurst(frameLine);
  if (ordinary && missed == 0) {
    float blank = measAt(pI + DELAY_Y + 116, pF).x;
    float tip = measAt(pI + DELAY_Y + 8, pF).y;
    clampL += uClampS * (blank - clampL);
    float gain = clamp(40.0 / max(blank - tip, 1.0), uAgcRange.x, uAgcRange.y);
    agc = agc < 0.0 ? gain : agc + uAgcS * (gain - agc);
  }
  float g = agc < 0.0 ? 1.0 : agc;
  if (ordinary) {
    vec2 b = measAt(pI + DELAY_ZB + 84, pF).zw;
    vec2 ref = burst / max(length(burst), 1e-9);
    vec2 step_ = cmul(b, vec2(ref.x, -ref.y));
    lock += uLockS * (step_.x - lock);
    burstNoise += uLockS * (step_.y * step_.y - burstNoise);
    burst += uBurstS * (b - burst);
  }
  hLock += uHLockS * ((missed == 0 ? 1.0 : 0.0) - hLock);
  float strength = hLock > 0.5 ? lock * g / BURST : 0.0;
  float snr = lock / sqrt(max(burstNoise, 1e-9));
  colourOk = strength > uKiller.x && snr > uKiller.z;
  colourGood = strength > uKiller.y && snr > uKiller.w;
  if (parity != 0 && colour) {
    int row = lineNo - (parity == 1 ? 23 : 286);
    if (row >= 0 && row < 240) colourLines++;
  }
}

void main() {
  int slot = int(gl_FragCoord.x);
  readState(texelFetch(uS0, ivec2(0), 0), texelFetch(uS1, ivec2(0), 0), texelFetch(uS2, ivec2(0), 0),
            texelFetch(uS3, ivec2(0), 0), texelFetch(uS4, ivec2(0), 0), texelFetch(uS5, ivec2(0), 0));
  bool started = texelFetch(uS3, ivec2(0), 0).w > 0.5;
  bool valid = false;
  for (int k = 0; k < ${MAX_LINES}; k++) {
    if (k > slot) break;
    if (started) {
      lineNo++;
      since++;
      nextSync();
    } else {
      // Acquire: the first sync in the line from half a line into the signal.
      int base = ACQUIRE + DELAY_SYNC;
      pI = ACQUIRE; pF = 0.0;
      int bs = -(base % BLOCK);
      int blk = (base - base % BLOCK) / BLOCK;
      bool found = false;
      for (int i = 0; i < BLOCK + bs; i++) {
        float e = texelFetch(uEdge, at(base + i), 0).r;
        if (e >= 0.0) { pI = ACQUIRE + i; pF = e; found = true; break; }
      }
      for (int q = 1; !found && bs + BLOCK * q < LINE; q++) {
        float first = summ(blk + q).x;
        if (first >= 0.0) {
          int i = bs + BLOCK * q + int(floor(first));
          pI = ACQUIRE + i; pF = fract(first); found = true;
        }
      }
    }
    if (wrapN(uEnd - pI) <= MARGIN) { valid = false; break; }
    decodeLine();
    started = true;
    valid = true;
  }
  int fl = (colour ? 1 : 0) + (colourOk ? 2 : 0) + (colourGood ? 4 : 0);
  o0 = vec4(float(pI), pF, period, float(min(missed, 100000)));
  o1 = vec4(hLock, float(lineNo), float(since), float(parity));
  o2 = vec4(clampL, agc, burst);
  o3 = vec4(lock, burstNoise, float(fl), valid ? 1.0 : 0.0);
  o4 = vec4(float(syncedLines), float(colourLines), float(fields), float(lastParity + 4 * prevParity));
  o5 = vec4(lastSynced, lastColour, prevSynced, prevColour);
}`;

/** The decoder's state after this step: the last line it got to; or as it was. */
const CARRY_FS = `${HEADER}
uniform sampler2D uL0t, uL1t, uL2t, uL3t, uL4t, uL5t;
uniform sampler2D uS0, uS1, uS2, uS3, uS4, uS5;
layout(location = 0) out vec4 o0;
layout(location = 1) out vec4 o1;
layout(location = 2) out vec4 o2;
layout(location = 3) out vec4 o3;
layout(location = 4) out vec4 o4;
layout(location = 5) out vec4 o5;
void main() {
  for (int i = ${MAX_LINES - 1}; i >= 0; i--) {
    if (texelFetch(uL3t, ivec2(i, 0), 0).w > 0.5) {
      o0 = texelFetch(uL0t, ivec2(i, 0), 0); o1 = texelFetch(uL1t, ivec2(i, 0), 0);
      o2 = texelFetch(uL2t, ivec2(i, 0), 0); o3 = texelFetch(uL3t, ivec2(i, 0), 0);
      o4 = texelFetch(uL4t, ivec2(i, 0), 0); o5 = texelFetch(uL5t, ivec2(i, 0), 0);
      return;
    }
  }
  o0 = texelFetch(uS0, ivec2(0), 0); o1 = texelFetch(uS1, ivec2(0), 0);
  o2 = texelFetch(uS2, ivec2(0), 0); o3 = texelFetch(uS3, ivec2(0), 0);
  o4 = texelFetch(uS4, ivec2(0), 0); o5 = texelFetch(uS5, ivec2(0), 0);
}`;

/** Each decoded line that falls in the picture, as one row of its field: fields go in turn
 * into LAYERS frames of 480 rows, each row tagged with its field's number. */
const PICTURE_VS = `#version 300 es
precision highp float;
precision highp int;
precision highp sampler2D;
uniform sampler2D uL0t, uL1t, uL2t, uL3t, uL4t;
uniform float uAccMax;
flat out int vP;
flat out float vF, vClamp, vAgc, vTag;
flat out vec2 vChroma;
void main() {
  int i = gl_InstanceID;
  vec4 s0 = texelFetch(uL0t, ivec2(i, 0), 0), s1 = texelFetch(uL1t, ivec2(i, 0), 0);
  vec4 s2 = texelFetch(uL2t, ivec2(i, 0), 0), s3 = texelFetch(uL3t, ivec2(i, 0), 0);
  int field = int(texelFetch(uL4t, ivec2(i, 0), 0).z);
  int parity = int(s1.w);
  int row = int(s1.y) - (parity == 1 ? 23 : 286);
  gl_Position = vec4(2.0, 2.0, 0.0, 1.0);
  if (s3.w < 0.5 || parity == 0 || row < 0 || row >= 240) return;
  float frameRow = float(2 * row + (parity == 2 ? 0 : 1) + (field % ${LAYERS}) * ${ACTIVE_LINES});
  int v = gl_VertexID;
  float x = v == 1 || v == 2 || v == 4 ? 1.0 : -1.0;
  float y = v == 2 || v == 4 || v == 5 ? 1.0 : 0.0;
  gl_Position = vec4(x, (frameRow + y) / ${(LAYERS * ACTIVE_LINES) / 2}.0 - 1.0, 0.0, 1.0);
  vP = int(s0.x);
  vF = s0.y;
  vClamp = s2.x;
  vAgc = s2.y < 0.0 ? 1.0 : s2.y;
  vTag = float(field);
  vChroma = vec2(0);
  if ((int(s3.z) & 1) != 0) {
    // Colour: turned so the burst is at 180 degrees on U, its gain set by the burst (ACC).
    vec2 b = s2.zw;
    float acc = min(20.0 / max(length(b), 1e-6), uAccMax);
    float a = 3.14159265358979 / 2.0 - atan(b.y, b.x);
    vChroma = vec2(cos(a), sin(a)) * acc / 92.5;
  }
}`;

/** One line of picture, Y'UV: the notch's luma and chroma, or the comb's (decode _Comb) where
 * this line and the last agree. */
const PICTURE_FS = `${HEADER}
uniform sampler2D uSyncY;
uniform sampler2D uChroma;
uniform sampler2D uComb;
uniform bool uUseComb;
flat in int vP;
flat in float vF, vClamp, vAgc, vTag;
flat in vec2 vChroma;
out vec4 o;
float lumaAt(int n) { return texelFetch(uSyncY, at(n), 0).g; }
vec2 chromaAt(int n) { return texelFetch(uChroma, at(n), 0).rg; }
/** The comb's luma: the notch's, plus the chroma band of this line and the last, halved. */
float combLuma(int n) { return lumaAt(n) + 0.5 * (texelFetch(uComb, at(n), 0).r + texelFetch(uComb, at(n - LINE), 0).r); }
/** The comb's chroma: the subcarrier turns over from line to line, so at baseband the two
 * lines' sum, halved. */
vec2 combChroma(int n) { return 0.5 * (chromaAt(n) + chromaAt(n - LINE)); }
/** How far to trust the notch: a vertical edge in the luma, or the colour changing. */
float notchWeight(int n) {
  float edge = abs(texelFetch(uComb, at(n), 0).g - texelFetch(uComb, at(n - LINE), 0).g);
  float here = length(chromaAt(n));
  float there = length(chromaAt(n - LINE));
  float change = abs(here - there) / (here + there + 4.0);
  return clamp(max((edge - 4.0) / 8.0, (change - 0.2) / 0.3), 0.0, 1.0);
}
void main() {
  int t = vP + 135 + int(gl_FragCoord.x);
  float y = mix(lumaAt(t + 35), lumaAt(t + 36), vF);
  vec2 z = mix(chromaAt(t + 50), chromaAt(t + 51), vF);
  if (uUseComb) {
    float w = mix(notchWeight(t + 50), notchWeight(t + 51), vF);
    y = w * y + (1.0 - w) * mix(combLuma(t + 35), combLuma(t + 36), vF);
    z = w * z + (1.0 - w) * mix(combChroma(t + 50), combChroma(t + 51), vF);
  }
  vec2 c = cmul(z, vChroma);
  o = vec4(((y - vClamp) * vAgc - SETUP) / SPAN, -c.y, c.x, vTag);
}`;

/** pipeline.AnalogVideo._picture: the last two whole fields woven (field 2 on the even
 * rows), or the last line-doubled, as R'G'B', 754 x 480, top row first. A field with too few
 * syncs shows the decoder's no-signal screen. */
const FRAME_FS = `#version 300 es
precision highp float;
precision highp int;
precision highp sampler2D;
uniform sampler2D uScreen;
uniform sampler2D uS4, uS5;
uniform bool uWeave;
uniform float uLostBelow;
uniform int uOnLoss; // 0 snow, 1 blue, 2 black
out vec4 o;
void main() {
  ivec2 p = ivec2(gl_FragCoord.xy);
  vec4 s4 = texelFetch(uS4, ivec2(0), 0), s5 = texelFetch(uS5, ivec2(0), 0);
  int last = int(s4.z) - 1;
  int prev = last - 1;
  int lastParity = int(s4.w) & 3, prevParity = int(s4.w) >> 2;
  if (last < 1) { o = vec4(0, 0, 0, 1); return; }
  bool weave = uWeave && prev >= 1 && prevParity != lastParity;
  int want = p.y % 2 == 0 ? 2 : 1;
  bool usePrev = weave && lastParity != want;
  int field = usePrev ? prev : last;
  int parity = usePrev ? prevParity : lastParity;
  float synced = usePrev ? s5.z : s5.x;
  int row = 2 * (p.y / 2) + (parity == 2 ? 0 : 1);
  vec4 px = texelFetch(uScreen, ivec2(p.x, (field % ${LAYERS}) * ${ACTIVE_LINES} + row), 0);
  vec3 yuv = px.a == float(field) ? px.rgb : vec3(0);
  if (synced < uLostBelow && uOnLoss != 0) {
    yuv = uOnLoss == 1 ? vec3(0.114 * 0.75, 0.492111 * (0.75 - 0.114 * 0.75), 0.877283 * (0.0 - 0.114 * 0.75)) : vec3(0);
  }
  float r = yuv.x + yuv.z / 0.877283;
  float b = yuv.x + yuv.y / 0.492111;
  float g = (yuv.x - 0.299 * r - 0.114 * b) / 0.587;
  o = vec4(clamp(vec3(r, g, b), 0.0, 1.0), 1);
}`;

/** The picture (or the recorder's) to the canvas, scaled. */
const DISPLAY_FS = `#version 300 es
precision highp float;
uniform sampler2D uPicture;
uniform vec2 uSize;
out vec4 o;
void main() {
  vec2 uv = gl_FragCoord.xy / uSize;
  o = vec4(texture(uPicture, vec2(uv.x, 1.0 - uv.y)).rgb, 1);
}`;

// -- the chain ------------------------------------------------------------------------------

const clone = (x) => JSON.parse(JSON.stringify(x));

function merge(base, over) {
  for (const [k, v] of Object.entries(over ?? {})) {
    if (v && typeof v === "object" && !Array.isArray(v) && base[k] && typeof base[k] === "object") merge(base[k], v);
    else base[k] = clone(v);
  }
  return base;
}

export class AnalogFeed {
  /**
   * @param {HTMLCanvasElement | OffscreenCanvas} canvas where the picture goes
   * @param {object} settings `link`, `decoder`, `deinterlace`, `dvr`, `seed`, as `set` takes
   * @param {{fit?: boolean}} options fit: size the canvas to its CSS box (the default); or
   *   keep the size it has
   */
  constructor(canvas, settings = {}, { fit = true } = {}) {
    this.canvas = canvas;
    this.fit = fit && typeof canvas.clientWidth === "number";
    const gl = canvas.getContext("webgl2", { alpha: false, antialias: false, depth: false, stencil: false });
    this.gl = gl;
    /** False where WebGL2 with float render targets and six draw buffers is missing. */
    this.ok = Boolean(gl?.getExtension("EXT_color_buffer_float")) && gl.getParameter(gl.MAX_DRAW_BUFFERS) >= 6;
    if (!this.ok) return;
    this.settings = clone(DEFAULTS);
    this.seed = (Math.random() * 2 ** 32) >>> 0;
    try {
      this._programs();
      this._textures();
    } catch (err) {
      console.error("analog feed off:", err);
      this.ok = false;
      return;
    }
    this.set(settings);
    this.reset();
  }

  /** Change the settings, from the next line: `link` (with `multipath`, a list of echoes),
   * `decoder`, `deinterlace` ("weave" or "bob"), `dvr` (null, or quality, one_field, size),
   * `seed`. Each is merged into what is set; the signal carries on. */
  set({ seed, ...settings } = {}) {
    if (!this.ok) return;
    if (seed !== undefined) this.seed = seed >>> 0;
    if ("dvr" in settings) this.settings.dvr = settings.dvr ? merge(clone(DVR), settings.dvr) : null;
    const { dvr, ...rest } = settings;
    merge(this.settings, rest);
    this._retap();
  }

  /** Carrier to noise, dB. */
  get cnrDb() {
    return this.settings?.link.cnr_db;
  }

  set cnrDb(db) {
    if (this.ok) this.settings.link.cnr_db = db;
  }

  /** Start the signal again: the decoder has to find it. */
  reset() {
    if (!this.ok) return;
    const gl = this.gl;
    this._line = 0;
    this._carry = 0;
    this._last = null;
    this._dvrBusy = false;
    this._dvrShown = false;
    this._rasterOf = null;
    for (const fb of this._clearable) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
    }
    // The decoder's state before it has seen anything (decode.VideoDecoder.__init__).
    const initial = [
      [0, 0, LINE, 0],
      [1, 0, this.settings.decoder.v_accept_after, 0],
      [0, -1, 0, 20],
      [20, 0, 7, 0],
      [0, 0, 0, 0],
      [0, 0, 0, 0],
    ];
    for (const st of this.state) {
      initial.forEach((v, i) => {
        gl.bindTexture(gl.TEXTURE_2D, st.tex[i]);
        gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, 1, 1, gl.RGBA, gl.FLOAT, new Float32Array(v));
      });
    }
  }

  /**
   * One animation frame: the lines due since the last, from `source` (the camera's picture:
   * an image, canvas, video or bitmap), with `osd` (a canvas of the OSD chip's pixels, one
   * per field line; or null) put in as the chip does; then the picture to the canvas.
   * @param {TexImageSource} source
   * @param {{canvas: HTMLCanvasElement, top: number, changed: boolean} | null} osd
   * @param {number} now performance.now()
   */
  frame(source, osd, now) {
    if (!this.ok) return;
    const due = this._last === null ? 263 : ((now - this._last) / 1000) * LINE_RATE + this._carry;
    this._last = now;
    const n = Math.min(Math.floor(due), MAX_BATCH);
    this._carry = Math.min(due - Math.floor(due), 1);
    if (n > 0) {
      this._camera(source);
      this._osd(osd);
      this._run(n, osd);
      this._frame();
      if (this.settings.dvr) this._record(now);
    }
    this.draw();
  }

  /** Exactly `lines` lines of `source` through the chain, as fast as it goes, then the
   * picture made (not drawn): for stills, sweeps and tests. Every 525 lines is one frame of
   * the Python's AnalogVideo.show. */
  run(source, lines, osd = null) {
    if (!this.ok) return;
    this._camera(source);
    this._osd(osd);
    for (let done = 0; done < lines; ) {
      const n = Math.min(lines - done, 263);
      this._run(n, osd);
      done += n;
    }
    this._frame();
  }

  /** How the signal was for the picture made last (pipeline.Shown): the share of its lines
   * with a sync and in colour, over the fields it shows. */
  stats() {
    if (!this.ok) return { synced: 0, colour: 0 };
    const [s4, s5] = [4, 5].map((i) => this._readState(i));
    const last = s4[2] - 1;
    if (last < 1) return { synced: 0, colour: 0 };
    const lastParity = s4[3] & 3;
    const prevParity = s4[3] >> 2;
    const s = this.settings;
    const weave = s.deinterlace === "weave" && !(s.dvr && s.dvr.one_field) && last - 1 >= 1 && prevParity !== lastParity;
    return weave ? { synced: (s5[0] + s5[2]) / 2, colour: (s5[1] + s5[3]) / 2 } : { synced: s5[0], colour: s5[1] };
  }

  /** The picture made last, 754 x 480 RGBA, top row first: as the goggles show it, before
   * any recorder. */
  pixels() {
    const gl = this.gl;
    const out = new Uint8Array(ACTIVE * ACTIVE_LINES * 4);
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.t.frame.fb);
    gl.readBuffer(gl.COLOR_ATTACHMENT0);
    gl.readPixels(0, 0, ACTIVE, ACTIVE_LINES, gl.RGBA, gl.UNSIGNED_BYTE, out);
    return out;
  }

  /** The picture made last as the recorder keeps it (with `dvr` set), or as shown: a canvas
   * at the recorder's size, or 754 x 480. */
  async recorded() {
    const shown = new OffscreenCanvas(ACTIVE, ACTIVE_LINES);
    shown.getContext("2d").putImageData(new ImageData(new Uint8ClampedArray(this.pixels().buffer), ACTIVE, ACTIVE_LINES), 0, 0);
    const dvr = this.settings.dvr;
    if (!dvr) return shown;
    const [w, h] = dvr.size;
    const sized = new OffscreenCanvas(w, h);
    const ctx = sized.getContext("2d");
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(shown, 0, 0, w, h);
    const blob = await sized.convertToBlob({ type: "image/jpeg", quality: dvr.quality / 100 });
    const decoded = new OffscreenCanvas(w, h);
    decoded.getContext("2d").drawImage(await createImageBitmap(blob), 0, 0);
    return decoded;
  }

  /** The picture to the canvas: the recorder's, with one set and recorded. */
  draw() {
    if (!this.ok) return;
    const gl = this.gl;
    const c = this.canvas;
    if (this.fit) {
      const dpr = globalThis.devicePixelRatio || 1;
      const w = Math.max(1, Math.round(c.clientWidth * dpr));
      const h = Math.max(1, Math.round(c.clientHeight * dpr));
      if (c.width !== w || c.height !== h) {
        c.width = w;
        c.height = h;
      }
    }
    const picture = this.settings.dvr && this._dvrShown ? this.dvrTex : this.t.frame.tex[0];
    this._bind("display", null, { uPicture: picture, uSize: [c.width, c.height] });
    gl.viewport(0, 0, c.width, c.height);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
  }

  // -- inside -------------------------------------------------------------------------------

  _programs() {
    const gl = this.gl;
    const compile = (type, src) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) ?? "shader");
      return s;
    };
    const program = (fs, vs = QUAD_VS) => {
      const p = gl.createProgram();
      gl.attachShader(p, compile(gl.VERTEX_SHADER, vs));
      gl.attachShader(p, compile(gl.FRAGMENT_SHADER, fs));
      gl.linkProgram(p);
      if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) ?? "program");
      const uniforms = {};
      const n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
      for (let i = 0; i < n; i++) {
        const info = gl.getActiveUniform(p, i);
        const name = info.name.replace(/\[0\]$/, "");
        uniforms[name] = { loc: gl.getUniformLocation(p, info.name), type: info.type };
      }
      return { p, u: uniforms };
    };
    this.prog = {
      raster: program(RASTER_FS),
      encode: program(ENCODE_FS),
      freq: program(FREQ_FS),
      rx: program(RX_FS),
      if: program(IF_FS),
      disc: program(DISC_FS),
      video: program(VIDEO_FS),
      filt: program(FILT_FS),
      slice: program(SLICE_FS),
      vint: program(VINT_FS),
      meas: program(MEAS_FS),
      summ: program(SUMM_FS),
      lines: program(LINES_FS),
      carry: program(CARRY_FS),
      picture: program(PICTURE_FS, PICTURE_VS),
      frame: program(FRAME_FS),
      display: program(DISPLAY_FS),
    };
  }

  _texture(w, h, internal, linear = false) {
    const gl = this.gl;
    const t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texStorage2D(gl.TEXTURE_2D, 1, internal, w, h);
    const filter = linear ? gl.LINEAR : gl.NEAREST;
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    return t;
  }

  _textures() {
    const gl = this.gl;
    const formats = { r: gl.R32F, rg: gl.RG32F, rgba: gl.RGBA32F, rgba8: gl.RGBA8 };
    this._clearable = [];
    const target = (w, h, ...formatList) => {
      const tex = formatList.map((f) => this._texture(w, h, formats[f], f === "rgba8"));
      const fb = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
      tex.forEach((t, i) => gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0 + i, gl.TEXTURE_2D, t, 0));
      gl.drawBuffers(tex.map((_, i) => gl.COLOR_ATTACHMENT0 + i));
      this._clearable.push(fb);
      return { fb, tex, w, h };
    };
    const RL = 2 * LINE;
    const six = ["rgba", "rgba", "rgba", "rgba", "rgba", "rgba"];
    this.t = {
      raster: target(ACTIVE, ACTIVE_LINES, "rgba"),
      comp: target(LINE, LINES, "r"),
      freq: target(RL, LINES, "r"),
      rx: target(RL, LINES, "r", "rg"),
      if: target(RL, LINES, "rg"),
      disc: target(RL, LINES, "r"),
      video: target(LINE, LINES, "r"),
      filt: target(LINE, LINES, "rg", "rgba", "rg"),
      slice: target(LINE, LINES, "r"),
      vint: target(LINE, LINES, "r"),
      meas: target(LINE, LINES, "r", "rgba"),
      summ: target(LINE / BLOCK, LINES, "rgba"),
      lines: target(MAX_LINES, 1, ...six),
      screen: target(ACTIVE, LAYERS * ACTIVE_LINES, "rgba"),
      frame: target(ACTIVE, ACTIVE_LINES, "rgba8"),
    };
    this.state = [target(1, 1, ...six), target(1, 1, ...six)];
    this._clearable = this._clearable.filter((fb) => !this.state.some((s) => s.fb === fb));
    this.cam = null;
    this._camSize = [0, 0];
    this._rasterH = null;
    this._rasterOf = null;
    this.osd = this._texture(1, 1, gl.RGBA8);
    this._osdSize = [0, 0];
    this.dvrTex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.dvrTex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    this.taps = this._texture(128, Object.keys(TAP).length, gl.R32F);
    this._tapsFor = null;
  }

  /** Every filter's taps, a row each (TAP), for the settings: only when they change. */
  _retap() {
    const { link, decoder } = this.settings;
    const key = JSON.stringify([
      link.if_bandwidth_hz,
      link.video_bandwidth_hz,
      decoder.sync_bandwidth_hz,
      decoder.luma_bandwidth_hz,
      decoder.chroma_bandwidth_hz,
      decoder.chroma_lowpass_hz,
    ]);
    if (key === this._tapsFor) return;
    this._tapsFor = key;
    const dec = decoderKernels(decoder);
    const rows = [];
    rows[TAP.encY] = lowpass(31, 4.2e6, FS);
    rows[TAP.encC] = lowpass(41, 1.3e6, FS);
    rows[TAP.up] = lowpass(63, 5.5e6, FS_RF).map((x) => 2 * x);
    rows[TAP.if] = lowpass(63, link.if_bandwidth_hz / 2, FS_RF);
    rows[TAP.video] = lowpass(63, link.video_bandwidth_hz, FS_RF);
    rows[TAP.sync] = dec.sync;
    rows[TAP.luma] = dec.luma;
    rows[TAP.lumaBp] = dec.lumaBp;
    rows[TAP.zr] = dec.zr;
    rows[TAP.zi] = dec.zi;
    rows[TAP.br] = dec.br;
    rows[TAP.bi] = dec.bi;
    rows[TAP.burst] = convolve(new Array(32).fill(1), smoothing(5));
    rows[TAP.edge] = dec.edge;
    const width = 128;
    const data = new Float32Array(width * rows.length);
    rows.forEach((r, i) => data.set(r, i * width));
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.taps);
    gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, width, rows.length, gl.RED, gl.FLOAT, data);
  }

  /** The camera's picture into the raster: again for a video or canvas, once for a still. */
  _camera(source) {
    const gl = this.gl;
    const still = (typeof HTMLImageElement !== "undefined" && source instanceof HTMLImageElement) || (typeof ImageBitmap !== "undefined" && source instanceof ImageBitmap);
    if (still && source === this._rasterOf) return;
    this._rasterOf = still ? source : null;
    const w = source.videoWidth || source.naturalWidth || source.width;
    const h = source.videoHeight || source.naturalHeight || source.height;
    if (!w || !h) return;
    if (!this.cam || w !== this._camSize[0] || h !== this._camSize[1]) {
      if (this.cam) gl.deleteTexture(this.cam);
      if (this._rasterH) {
        gl.deleteTexture(this._rasterH.tex[0]);
        gl.deleteFramebuffer(this._rasterH.fb);
      }
      this.cam = this._texture(w, h, gl.RGBA8);
      const tex = this._texture(ACTIVE, h, gl.RGBA32F);
      const fb = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
      this._rasterH = { fb, tex: [tex], w: ACTIVE, h };
      this._camSize = [w, h];
    }
    gl.bindTexture(gl.TEXTURE_2D, this.cam);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
    gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, gl.RGBA, gl.UNSIGNED_BYTE, source);
    this._pass("raster", this._rasterH, { uSrc: this.cam, uAxis: 0, uIn: w });
    this._pass("raster", this.t.raster, { uSrc: this._rasterH.tex[0], uAxis: 1, uIn: h });
  }

  _osd(osd) {
    if (!osd?.changed) return;
    const gl = this.gl;
    gl.deleteTexture(this.osd);
    this.osd = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.osd);
    for (const [k, v] of [
      [gl.TEXTURE_MIN_FILTER, gl.NEAREST],
      [gl.TEXTURE_MAG_FILTER, gl.NEAREST],
      [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE],
      [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE],
    ])
      gl.texParameteri(gl.TEXTURE_2D, k, v);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, osd.canvas);
    this._osdSize = [osd.canvas.width, osd.canvas.height];
    osd.changed = false;
  }

  /** The echoes, for the line `l0` starts at: level, delay in samples, turn there and turn a
   * sample. Turns are taken round in double precision here, so the GPU's stay small. */
  _echoes(l0) {
    const echoes = this.settings.link.multipath.slice(0, MAX_ECHOES);
    const out = new Float32Array(4 * MAX_ECHOES);
    const t0 = (l0 * 2 * LINE) / FS_RF;
    echoes.forEach((e, i) => {
      const delay = Math.min(Math.max(e.delay_s, 0), MAX_ECHO_DELAY_S) * FS_RF;
      const turn = ((e.phase_deg ?? 0) * Math.PI) / 180 + 2 * Math.PI * (((e.doppler_hz ?? 0) * t0) % 1);
      out.set([10 ** (e.level_db / 20), delay, turn, (2 * Math.PI * (e.doppler_hz ?? 0)) / FS_RF], 4 * i);
    });
    return { uEchoes: echoes.length, uEcho: out };
  }

  _run(n, osd) {
    const t = this.t;
    const { link, decoder: d } = this.settings;
    const start = this._line;
    this._line += n;
    const end = this._line;
    const radPerIre = ((link.deviation_hz / 140) * 2 * Math.PI) / FS_RF;
    const n0 = 1 / (10 ** (link.cnr_db / 10) * link.if_bandwidth_hz);
    const sigma = Math.sqrt((n0 * FS_RF) / 2);
    // The streams that look ahead are redone a line back, where they lacked the new lines.
    const back = Math.max(start - 1, 0);
    const osdSize = osd ? [this._osdSize[0], this._osdSize[1], osd.top] : [0, 0, 0];
    this._rows("encode", t.comp, start, end, { uRaster: t.raster.tex[0], uOsd: this.osd, uOsdSize: osdSize });
    this._rows("freq", t.freq, start, end, { uComp: t.comp.tex[0], uRadPerIre: radPerIre });
    const rx = {
      uFreq: t.freq.tex[0],
      uSigma: sigma,
      uSeed: this.seed,
      uOffset: (2 * Math.PI * link.carrier_offset_hz) / FS_RF,
    };
    this._rows("rx", t.rx, start, end, rx, (l0) => this._echoes(l0));
    this._rows("if", t.if, start, end, { uFreq: t.rx.tex[0], uRx: t.rx.tex[1] });
    this._rows("disc", t.disc, start, end, { uIf: t.if.tex[0], uFreq: t.rx.tex[0], uRadPerIre: radPerIre });
    this._rows("video", t.video, start, end, { uDisc: t.disc.tex[0] });
    this._rows("filt", t.filt, start, end, { uVideo: t.video.tex[0] });
    this._rows("slice", t.slice, start, end, { uSyncY: t.filt.tex[0], uSlice: d.sync_slice_ire });
    this._rows("vint", t.vint, start, end, { uSlice: t.slice.tex[0] });
    this._rows("meas", t.meas, back, end, { uSyncY: t.filt.tex[0], uChroma: t.filt.tex[1], uSlice: d.sync_slice_ire });
    this._rows("summ", t.summ, back, end, { uEdge: t.meas.tex[0], uV: t.vint.tex[0] });
    // The decoder, from its state after the last step, then that state carried on.
    const [from, to] = this.state;
    const s = Object.fromEntries(from.tex.map((tex, i) => [`uS${i}`, tex]));
    this._pass("lines", t.lines, {
      ...s,
      uEdge: t.meas.tex[0],
      uSumm: t.summ.tex[0],
      uMeas: t.meas.tex[1],
      uV: t.vint.tex[0],
      uEnd: (end % LINES) * LINE,
      uHWindow: Math.round(d.h_window),
      uSearchAfter: Math.round(d.h_search_after),
      uVAccept: Math.round(d.v_accept_after),
      uVFree: Math.round(d.v_free_lines),
      uPhaseGain: d.h_phase_gain,
      uFreqGain: d.h_freq_gain,
      uClampS: d.clamp_smoothing,
      uAgcS: d.agc_smoothing,
      uBurstS: d.burst_smoothing,
      uLockS: d.lock_smoothing,
      uHLockS: d.h_lock_smoothing,
      uAgcRange: d.agc_range,
      uKiller: [d.killer_off, d.killer_on, d.killer_snr_off, d.killer_snr_on],
    });
    const lines = Object.fromEntries(t.lines.tex.map((tex, i) => [`uL${i}t`, tex]));
    this._pass("carry", to, { ...lines, ...s });
    this.state = [to, from];
    const gl = this.gl;
    this._bind("picture", t.screen, {
      ...lines,
      uAccMax: d.acc_max_gain,
      uSyncY: t.filt.tex[0],
      uChroma: t.filt.tex[1],
      uComb: t.filt.tex[2],
      uUseComb: d.yc === "comb",
    });
    gl.viewport(0, 0, t.screen.w, t.screen.h);
    gl.drawArraysInstanced(gl.TRIANGLES, 0, 6, MAX_LINES);
  }

  /** The fields shown, into the picture (pipeline.AnalogVideo._picture). */
  _frame() {
    const { deinterlace, dvr, decoder: d } = this.settings;
    const [, , , , s4, s5] = this.state[0].tex;
    this._pass("frame", this.t.frame, {
      uScreen: this.t.screen.tex[0],
      uS4: s4,
      uS5: s5,
      uWeave: deinterlace === "weave" && !(dvr && dvr.one_field),
      uLostBelow: d.lost_below,
      uOnLoss: { snow: 0, blue: 1, black: 2 }[d.on_loss] ?? 0,
    });
  }

  /** The recorder, live: the picture compressed as it keeps it, at most 30 times a second
   * and one at a time; shown when done. */
  _record(now) {
    if (this._dvrBusy || now - (this._dvrAt ?? -1e9) < 1000 / 30) return;
    this._dvrBusy = true;
    this._dvrAt = now;
    this.recorded()
      .then((canvas) => {
        if (!this.settings.dvr) return;
        const gl = this.gl;
        gl.bindTexture(gl.TEXTURE_2D, this.dvrTex);
        gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, canvas);
        this._dvrShown = true;
      })
      .finally(() => (this._dvrBusy = false));
  }

  _readState(i) {
    const gl = this.gl;
    const out = new Float32Array(4);
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.state[0].fb);
    gl.readBuffer(gl.COLOR_ATTACHMENT0 + i);
    gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.FLOAT, out);
    return out;
  }

  /** Program `name` drawing to `target` (null: the canvas), with `uniforms`: textures bound
   * in turn, the rest by the uniform's type. */
  _bind(name, target, uniforms) {
    const gl = this.gl;
    const { p, u } = this.prog[name];
    gl.useProgram(p);
    gl.bindFramebuffer(gl.FRAMEBUFFER, target ? target.fb : null);
    gl.disable(gl.BLEND);
    gl.disable(gl.DEPTH_TEST);
    this._unit = 0;
    this._set(u, { uTaps: this.taps, ...uniforms });
    return u;
  }

  _set(u, uniforms) {
    const gl = this.gl;
    for (const [key, value] of Object.entries(uniforms)) {
      const info = u[key];
      if (!info) continue;
      const { loc, type } = info;
      switch (type) {
        case gl.SAMPLER_2D:
          gl.activeTexture(gl.TEXTURE0 + this._unit);
          gl.bindTexture(gl.TEXTURE_2D, value);
          gl.uniform1i(loc, this._unit++);
          break;
        case gl.FLOAT:
          gl.uniform1f(loc, value);
          break;
        case gl.FLOAT_VEC2:
          gl.uniform2fv(loc, value);
          break;
        case gl.FLOAT_VEC4:
          gl.uniform4fv(loc, value);
          break;
        case gl.INT_VEC3:
          gl.uniform3iv(loc, value);
          break;
        case gl.UNSIGNED_INT:
          gl.uniform1ui(loc, value);
          break;
        case gl.BOOL:
          gl.uniform1i(loc, value ? 1 : 0);
          break;
        default:
          gl.uniform1i(loc, value);
      }
    }
  }

  _pass(name, target, uniforms) {
    const gl = this.gl;
    this._bind(name, target, uniforms);
    gl.viewport(0, 0, target.w, target.h);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
  }

  /** Program `name` over the ring's rows for lines `from` to `to`, in at most two pieces;
   * `perPiece(l0)` gives uniforms that depend on where a piece starts. */
  _rows(name, target, from, to, uniforms, perPiece = null) {
    const gl = this.gl;
    const u = this._bind(name, target, uniforms);
    for (let l = from; l < to; ) {
      const r0 = l % LINES;
      const count = Math.min(to - l, LINES - r0);
      if (u.uL0) gl.uniform1i(u.uL0.loc, l);
      if (perPiece) this._set(u, perPiece(l));
      gl.viewport(0, r0, target.w, count);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      l += count;
    }
  }
}
