import { CreateRunForm } from "@/components/runs/create-run-form";

export default function CreateRunPage() {
  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-normal">Create Run</h1>
        <p className="mt-1 text-sm text-zinc-500">Choose a supervisor and provide order context.</p>
      </div>
      <CreateRunForm />
    </div>
  );
}
