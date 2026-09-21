const SECURITY_LINK_TOKEN_PATTERN = /^[A-Za-z0-9_-]{43}$/;

export function takeSecurityLinkTokenFromFragment(
  location: Pick<Location, "hash" | "pathname" | "search">,
  history: Pick<History, "replaceState" | "state">,
): string | null {
  const fragment = location.hash.startsWith("#") ? location.hash.slice(1) : "";
  const token = new URLSearchParams(fragment).get("token");

  if (location.hash !== "") {
    history.replaceState(history.state, "", `${location.pathname}${location.search}`);
  }

  return token !== null && SECURITY_LINK_TOKEN_PATTERN.test(token) ? token : null;
}
