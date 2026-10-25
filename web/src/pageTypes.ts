import { age, type Json } from "./api";

export interface PageProps {
  live: Json;
  config: Json;
  profile: string;
  act: (
    path: string,
    body?: unknown,
    method?: string,
  ) => Promise<Json | undefined>;
  busy: boolean;
}

export const symbols = ["NQ=F", "ES=F", "YM=F"];

export const tone = (value: number) => (value >= 0 ? "positive" : "negative");

export const fresh = (stamp: string) => age(stamp) < 45;
