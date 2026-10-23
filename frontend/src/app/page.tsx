import Workspace from "@/components/workspace";
export const dynamic = "force-dynamic";

export default function Page() {
  return <Workspace demoEnabled={process.env.DEMO_MODE === "true"} />;
}
