import { redirect } from "next/navigation";

export default function Home() {
  // In a real app, we'd check auth and route to /ops or /portal based on role
  // For Phase 0, we'll just redirect to the portal to show the app shell is wired up
  redirect("/portal");
}
