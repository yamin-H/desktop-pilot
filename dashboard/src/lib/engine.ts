import { approach } from "./scale";

// The chart shows the moment slightly behind real time: one sample interval plus margin.
// Then the line at the right edge is always drawn between two known samples, so nothing
// already on screen is ever redrawn when the next sample arrives.
export const DISPLAY_LAG_MS = 1200;

const TIME_TAU_MS = 280; // how quickly the chart catches up after you stop hovering
const WINDOW_TAU_MS = 240; // how quickly it zooms when the time range changes
const Y_TAU_MS = 260; // how quickly the price axis rescales

/** The animated state of the chart: displayed time, time range and price range. */
export class ChartMotion {
  now = 0;
  windowMs: number;
  y: [number, number] | null = null;
  private frozen: number | null = null;
  private lag = 0;
  private started = false;

  constructor(windowMs: number) {
    this.windowMs = windowMs;
  }

  /** Time follows the clock, freezes while the pointer hovers, and catches up smoothly after. */
  advanceTime(dtMs: number, realNow: number, hovering: boolean, animate: boolean): void {
    const live = realNow - DISPLAY_LAG_MS;
    if (!this.started) {
      this.started = true;
      this.now = live;
      return;
    }
    if (hovering) {
      if (this.frozen === null) this.frozen = this.now;
      this.lag = live - this.frozen;
      this.now = this.frozen;
      return;
    }
    if (this.frozen !== null) {
      this.lag = live - this.frozen;
      this.frozen = null;
    }
    this.lag = animate ? approach(this.lag, 0, dtMs, TIME_TAU_MS) : 0;
    this.now = live - this.lag;
  }

  advanceWindow(dtMs: number, target: number, animate: boolean): void {
    this.windowMs = animate ? approach(this.windowMs, target, dtMs, WINDOW_TAU_MS) : target;
  }

  advanceY(dtMs: number, target: [number, number] | null, animate: boolean): void {
    if (!target) return;
    if (!this.y || !animate) {
      this.y = [target[0], target[1]];
      return;
    }
    this.y = [
      approach(this.y[0], target[0], dtMs, Y_TAU_MS),
      approach(this.y[1], target[1], dtMs, Y_TAU_MS),
    ];
  }
}