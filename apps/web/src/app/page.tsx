import { redirect } from "next/navigation";

export default function Home() {
  // The operator console is the default landing; the client portal is a
  // separate, role-gated experience (see docs/footnote-product-docs.md §1.3).
  redirect("/ops");
}
