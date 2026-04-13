import { RunTimeline } from "@/modules/runs/components/run-timeline";

export default async function RunPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return <RunTimeline runId={runId} />;
}
