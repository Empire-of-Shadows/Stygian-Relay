import { Link } from "react-router-dom";
import { AppFooter } from "../_engine/components/AppFooter";

/**
 * Relay's footer: the shared engine footer, plus one relay-specific link.
 *
 * "Your data" sits next to the legal links on purpose. The privacy policy tells a member
 * what relay stores; this is the page where they do something about it, and a member who
 * has just read the policy is exactly the person looking for it.
 */
export function Footer() {
  return (
    <AppFooter
      brand="Empire of Shadows · Stygian Relay Dashboard"
      extraLinks={<Link to="/me/privacy">Your data</Link>}
    />
  );
}
