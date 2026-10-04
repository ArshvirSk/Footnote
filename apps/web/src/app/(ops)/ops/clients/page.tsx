import { redirect } from "next/navigation";

/** The websites flow moved to /ops/websites (kept as a permanent redirect). */
export default function ClientsRedirect() {
  redirect("/ops/websites");
}
