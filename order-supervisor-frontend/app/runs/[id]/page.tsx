import { RunDetailsPage } from "@/components/runs/run-details-page";

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <RunDetailsPage runId={id} />;
}
