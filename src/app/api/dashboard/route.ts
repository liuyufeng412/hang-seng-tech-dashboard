import { readFile } from "node:fs/promises";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";

import type { DashboardSnapshot, SessionKey } from "@/lib/dashboard-types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const sessionKeys = new Set<SessionKey>(["morning", "midday", "evening"]);
const datePattern = /^\d{4}-\d{2}-\d{2}$/;

async function readJson<T>(filePath: string): Promise<T> {
  return JSON.parse(await readFile(filePath, "utf8")) as T;
}

export async function GET(request: NextRequest) {
  const runtimeRoot = path.join(process.cwd(), "data", "runtime");
  try {
    const availability = await readJson<DashboardSnapshot["availability"] & { latestDate: string; latestSession: SessionKey }>(path.join(runtimeRoot, "index.json"));
    const requestedDate = request.nextUrl.searchParams.get("date") ?? availability.latestDate;
    const rawSession = request.nextUrl.searchParams.get("session") ?? availability.latestSession;
    if (!datePattern.test(requestedDate) || !sessionKeys.has(rawSession as SessionKey)) {
      return NextResponse.json({ error: "Invalid date or report session", availability }, { status: 400 });
    }
    const session = rawSession as SessionKey;
    const reportPath = path.join(runtimeRoot, "reports", requestedDate, `${session}.json`);
    const snapshot = await readJson<DashboardSnapshot>(reportPath);
    return NextResponse.json({ ...snapshot, availability }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown dashboard data error";
    return NextResponse.json(
      { error: "Data unavailable", detail: message, lastSuccessfulUpdate: null },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
