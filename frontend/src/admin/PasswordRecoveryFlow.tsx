import { FormEvent, useState } from "react";

type PasswordRecoveryFlowProps = { token: string | null };

export function PasswordRecoveryFlow({ token }: PasswordRecoveryFlowProps) {
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [state, setState] = useState<"ready" | "submitting" | "invalid" | "complete">(
    token === null ? "invalid" : "ready",
  );

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (token === null || state === "submitting") return;
    if (password.length < 12 || password.length > 128 || password.trim().length === 0 || password !== confirmation) {
      setPasswordError(password !== confirmation ? "Las contraseñas no coinciden." : "La contraseña debe tener entre 12 y 128 caracteres y no puede contener solo espacios.");
      return;
    }
    setPasswordError(null);
    setState("submitting");
    try {
      const response = await fetch("/api/admin/password-recovery/complete", {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        referrerPolicy: "no-referrer",
        body: JSON.stringify({ token, newPassword: password }),
      });
      setPassword("");
      setConfirmation("");
      if (response.ok) setState("complete");
      else if (response.status === 422) {
        setPasswordError("La contraseña no cumple los requisitos de seguridad. El enlace sigue disponible; intenta con otra.");
        setState("ready");
      } else setState("invalid");
    } catch {
      setPassword("");
      setConfirmation("");
      setState("invalid");
    }
  }

  return (
    <main className="activation-page">
      <header className="activation-header">
        <img className="activation-brand" src="/assets/brand/logo.jpeg" alt="Manita de Gato, salón de belleza" />
        <div><h1>Recuperación de contraseña</h1><p>Restablece el acceso a tu cuenta administrativa.</p></div>
      </header>
      <section className="activation-card" aria-labelledby="recovery-title">
        {state === "complete" ? (
          <div className="activation-complete">
            <div className="activation-complete__icon" aria-hidden="true">✓</div>
            <h2 id="recovery-title">Contraseña restablecida</h2>
            <p className="activation-lead">Por seguridad, inicia sesión con tu nueva contraseña y tu verificación en dos pasos. No se ha iniciado ninguna sesión.</p>
            <a className="activation-button activation-button--link" href="/admin/">Ir al inicio de sesión</a>
          </div>
        ) : state === "invalid" ? (
          <>
            <h2 id="recovery-title">No fue posible completar la recuperación</h2>
            <p className="activation-notice activation-notice--error" role="alert">Comprueba que las contraseñas coincidan y cumplan los requisitos, y que el enlace siga vigente.</p>
            <a className="activation-exit" href="/admin/">Volver al inicio de sesión</a>
          </>
        ) : (
          <form className="activation-form" onSubmit={(event) => void submit(event)}>
            <h2 id="recovery-title">Elige una contraseña nueva</h2>
            <p className="activation-lead">Usa entre 12 y 128 caracteres. Tu verificación en dos pasos seguirá siendo obligatoria.</p>
            <label className="activation-field" htmlFor="recovery-password">Nueva contraseña
              <input id="recovery-password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required aria-describedby="recovery-password-error" value={password} onChange={(event) => setPassword(event.target.value)} />
            </label>
            <label className="activation-field" htmlFor="recovery-confirmation">Confirmar contraseña
              <input id="recovery-confirmation" type="password" autoComplete="new-password" minLength={12} maxLength={128} required aria-describedby="recovery-password-error" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} />
            </label>
            {passwordError !== null ? <p className="activation-error" id="recovery-password-error" role="alert">{passwordError}</p> : <span id="recovery-password-error" />}
            <button className="activation-button" type="submit" disabled={state === "submitting" || token === null}>
              {state === "submitting" ? "Restableciendo…" : "Restablecer contraseña"}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
