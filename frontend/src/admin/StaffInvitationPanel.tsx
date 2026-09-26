import { FormEvent, useState } from "react";

type InvitationState =
  | { kind: "idle" }
  | { kind: "pending"; deliveryStatus: "accepted" | "failed"; message: string }
  | { kind: "forced"; deliveryStatus: "accepted" | "failed"; message: string }
  | { kind: "reset"; deliveryStatus: "accepted" | "failed"; message: string }
  | { kind: "cancelled"; message: string }
  | { kind: "error"; message: string };

type StaffInvitationPanelProps = {
  csrfToken: string;
  onSessionUnavailable: () => void;
};

export function StaffInvitationPanel({
  csrfToken,
  onSessionUnavailable,
}: StaffInvitationPanelProps) {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<InvitationState>({ kind: "idle" });
  const [submitting, setSubmitting] = useState(false);

  async function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await mutate("", { email });
  }

  async function mutate(path: "" | "/resend", body?: { email: string }) {
    if (submitting) return;
    setSubmitting(true);
    try {
      const response = await fetch(`/api/admin/staff-invitations${path}`, {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (response.status === 401) {
        onSessionUnavailable();
        return;
      }
      if (response.status === 403) {
        setState({
          kind: "error",
          message: "No tienes permiso para realizar esta operación.",
        });
        return;
      }
      if (!response.ok) throw new Error("staff invitation is unavailable");
      const payload: unknown = await response.json();
      if (!isInvitationResponse(payload)) throw new Error("staff invitation response is invalid");
      setEmail("");
      setState({
        kind: "pending",
        deliveryStatus: payload.deliveryStatus,
        message: payload.deliveryStatus === "accepted"
          ? "La invitación está pendiente y el enlace fue enviado."
          : payload.detail ?? "No se pudo enviar el correo. Puedes reenviar o cancelar la invitación.",
      });
    } catch {
      setState({ kind: "error", message: "No fue posible actualizar la invitación." });
    } finally {
      setSubmitting(false);
    }
  }

  async function cancel() {
    if (submitting) return;
    setSubmitting(true);
    try {
      const response = await fetch("/api/admin/staff-invitations/cancel", {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": csrfToken },
      });
      if (response.status === 401) {
        onSessionUnavailable();
        return;
      }
      if (response.status === 403) {
        setState({
          kind: "error",
          message: "No tienes permiso para realizar esta operación.",
        });
        return;
      }
      if (!response.ok) throw new Error("staff invitation cancellation is unavailable");
      setState({ kind: "cancelled", message: "La invitación fue cancelada. Ya puedes crear una nueva." });
    } catch {
      setState({ kind: "error", message: "No fue posible actualizar la invitación." });
    } finally {
      setSubmitting(false);
    }
  }

  async function forcePasswordReset() {
    if (submitting) return;
    const confirmed = window.confirm("La persona dejará de poder iniciar sesión con su contraseña actual y recibirá un enlace para crear una nueva. ¿Deseas continuar?");
    if (!confirmed) return;
    setSubmitting(true);
    try {
      const response = await fetch("/api/admin/staff-password-reset", {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": csrfToken },
      });
      if (response.status === 401) {
        onSessionUnavailable();
        return;
      }
      if (response.status === 403) {
        setState({ kind: "error", message: "No tienes permiso para realizar esta operación." });
        return;
      }
      const payload: unknown = await response.json();
      if (!response.ok || !isInvitationResponse(payload)) {
        throw new Error("forced staff password reset is unavailable");
      }
      setState({
        kind: "reset",
        deliveryStatus: payload.deliveryStatus,
        message: payload.deliveryStatus === "accepted"
          ? "Se envió al personal un enlace para crear una contraseña nueva."
          : payload.detail ?? "No se pudo enviar el enlace. La contraseña anterior ya no permite iniciar sesión.",
      });
    } catch {
      setState({ kind: "error", message: "No fue posible iniciar el restablecimiento de contraseña." });
    } finally {
      setSubmitting(false);
    }
  }

  const pending = state.kind === "pending";
  return (
    <main className="staff-access-page">
      <header className="staff-access-header">
        <p className="app-shell__eyebrow">Manita de Gato</p>
        <h1>Administración</h1>
        <p>Invita a una persona del negocio. Ella configurará su propia contraseña y verificación en dos pasos.</p>
      </header>
      <section className="staff-access-card" aria-labelledby="staff-invitation-title">
        <h2 id="staff-invitation-title">Acceso del personal</h2>
        {!pending ? (
          <form className="staff-access-form" onSubmit={(event) => void invite(event)}>
            <label htmlFor="staff-email">Correo del personal</label>
            <input id="staff-email" name="email" type="email" autoComplete="email" maxLength={254} required value={email} onChange={(event) => setEmail(event.target.value)} />
            <button type="submit" disabled={submitting}>{submitting ? "Enviando…" : "Enviar invitación"}</button>
          </form>
        ) : null}
        {state.kind !== "idle" ? (
          <p className={`staff-access-status${state.kind === "error" || ((state.kind === "pending" || state.kind === "forced" || state.kind === "reset") && state.deliveryStatus === "failed") ? " staff-access-status--error" : ""}`} role={state.kind === "error" || ((state.kind === "forced" || state.kind === "reset") && state.deliveryStatus === "failed") ? "alert" : "status"}>{state.message}</p>
        ) : null}
        {pending ? (
          <div className="staff-access-actions">
            <button type="button" disabled={submitting} onClick={() => void mutate("/resend")}>Reenviar invitación</button>
            <button className="staff-access-button--secondary" type="button" disabled={submitting} onClick={() => void cancel()}>Cancelar invitación</button>
          </div>
        ) : null}
        {state.kind !== "pending" && state.kind !== "forced" ? (
          <div className="staff-access-actions">
            <button type="button" disabled={submitting} onClick={() => void forcePasswordReset()}>
              {state.kind === "reset" ? "Enviar un enlace nuevo para crear contraseña" : "Enviar enlace para crear una contraseña nueva"}
            </button>
          </div>
        ) : null}
      </section>
    </main>
  );
}

function isInvitationResponse(value: unknown): value is { deliveryStatus: "accepted" | "failed"; detail?: string } {
  if (typeof value !== "object" || value === null || !("deliveryStatus" in value)) return false;
  const status = value.deliveryStatus;
  return status === "accepted" || status === "failed";
}
