import { Suspense } from "react";

import { Profile } from "@/components/settings/profile";

/** Settings → Profile: photo, name, what you do, email, and how you sign in. */
export default function Page() {
  return (
    // Reads the query (a message after linking GitHub), so under a Suspense boundary.
    <Suspense>
      <Profile />
    </Suspense>
  );
}
