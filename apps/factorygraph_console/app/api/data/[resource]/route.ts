import { NextRequest } from "next/server";
import { data } from "@/lib/server/backend";
import { failure } from "@/lib/server/security";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
async function handler(request: NextRequest, context: { params: Promise<{ resource: string }> }) {
  try {
    return await data(request, (await context.params).resource);
  } catch (error) {
    return failure(error);
  }
}
export { handler as GET, handler as POST };
