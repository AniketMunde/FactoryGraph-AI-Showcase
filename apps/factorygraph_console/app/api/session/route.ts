import { NextRequest, NextResponse } from "next/server";
import {
  boundary,
  failure,
  login,
  logout,
  publicSession,
  Rejection,
  session,
} from "@/lib/server/security";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(request: NextRequest) {
  try {
    boundary(request);
    return NextResponse.json({ authenticated: true, ...publicSession(session(request)) });
  } catch (error) {
    if (error instanceof Rejection && error.status === 401)
      return NextResponse.json({ authenticated: false });
    return failure(error);
  }
}
export async function POST(request: NextRequest) {
  try {
    return await login(request);
  } catch (error) {
    return failure(error);
  }
}
export async function DELETE(request: NextRequest) {
  try {
    return logout(request);
  } catch (error) {
    return failure(error);
  }
}
