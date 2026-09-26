import { useState } from "react";

export function OwnEmailChangeConfirmationFlow({ token }: { token: string | null }) {
  const [state, setState] = useState<"ready" | "submitting" | "invalid" | "complete">(
    token === null ? "invalid" : "ready",
  );

  async function confirm() {
    if (token === null || state !== "ready") return;
    setState("submitting");
    try {
      const response = await fetch("/api/admin/account/email-change/complete", {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        referrerPolicy: "no-referrer",
        body: JSON.stringify({ token }),
      });
      setState(response.ok ? "complete" : "invalid");
    } catch {
      setState("invalid");
    }
  }

  return (
    <main className="activation-page">
      <header className="activation-header">
        <img className="activation-brand" src="/assets/brand/logo.jpeg" alt="Manita de Gato, salón de belleza" />
        <div><h1>Cambio de correo</h1><p>Confirma el correo de tu cuenta administrativa.</p></div>
      </header>
      <section className="activation-card" aria-labelledby="email-change-confirmation-title">
        {state === "complete" ? (
          <div className="activation-complete">
            <div className="activation-complete__icon" aria-hidden="true">✓</div>
            <h2 id="email-change-confirmation-title">Correo cambiado</h2>
            <p className="activation-lead">Tus sesiones se cerraron. Enviamos un aviso al correo anterior y otro al nuevo.</p>
            <a className="activation-button activation-button--link" href="/admin/">Ir al inicio de sesión</a>
          </div>
        ) : state === "invalid" ? (
          <>
            <h2 id="email-change-confirmation-title">No fue posible confirmar el cambio</h2>
            <p className="activation-notice activation-notice--error" role="alert">Verifica que el enlace siga vigente. Tu correo anterior permanece activo si el cambio no se confirmó.</p>
            <a className="activation-exit" href="/admin/">Volver al inicio de sesión</a>
          </>
        ) : (
          <>
            <h2 id="email-change-confirmation-title">Confirmar correo nuevo</h2>
            <p className="activation-lead">Al confirmar, se cerrarán las sesiones de tu cuenta y recibirás un aviso en ambos correos.</p>
            <button className="activation-button" type="button" onClick={() => void confirm()} disabled={state === "submitting"}>
              {state === "submitting" ? "Confirmando…" : "Confirmar cambio de correo"}
            </button>
          </>
        )}
      </section>
    </main>
  );
}
