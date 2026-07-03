import { readFile } from "fs";
import type { Opts } from "./types";

export const LIMIT = 100;

export function parse(input: string): number {
  return Number(input) + LIMIT;
}

const double = (n: number): number => n * 2;

export class Store {
  size = 0;

  constructor(private opts: Opts) {
    this.size = 0;
  }

  add(item: string): void {
    this.size += 1;
  }
}
