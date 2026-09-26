import { FormEvent, useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";

type Setup = { provisioningUri: string; manualKey: string };
type ViewState =
  | { kind: "loading" }
  | { kind: "invalid" }
  | { kind: "ready"; setup: Setup }
  | { kind: "submitting"; setup: Setup }
  | { kind: "codes"; codes: readonly string[] };

const GENERIC_ERROR = "Este enlace o configuración no está disponible.";

export function LostFactorReplacementFlow({ token }: { token: string | null }) {
  const [state, setState] = useState<ViewState>(token === null ? { kind: "invalid" } : { kind: "loading" });
  const [code, setCode] = useState("");
  const [showManualKey, setShowManualKey] = useState(false);

  useEffect(() => {
    if (token === null) return;
    const controller = new AbortController();
    void fetch("/api/admin/totp-replacement/prepare-lost", {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      referrerPolicy: "no-referrer",
      body: JSON.stringify({ token }),
      signal: controller.signal,
    }).then(async (response) => {
      if (!response.ok) throw new Error(GENERIC_ERROR);
      const body = await response.json() as { totpSetup: Setup };
      if (!body.totpSetup?.manualKey || !body.totpSetup?.provisioningUri) throw new Error(GENERIC_ERROR);
      setState({ kind: "ready", setup: body.totpSetup });
    }).catch((error: unknown) => {
      if (!(error instanceof DOMException && error.name === "AbortError")) setState({ kind: "invalid" });
    });
    return () => controller.abort();
  }, [token]);

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (token === null || state.kind !== "ready" || !/^\d{6}$/.test(code)) return;
    const setup = state.setup;
    setState({ kind: "submitting", setup });
    try {
      const response = await fetch("/api/admin/totp-replacement/complete-lost", {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        referrerPolicy: "no-referrer",
        body: JSON.stringify({ token, totpCode: code }),
      });
      setCode("");
      if (!response.ok) throw new Error(GENERIC_ERROR);
      const body = await response.json() as { recoveryCodes: string[] };
      if (body.recoveryCodes.length !== 10) throw new Error(GENERIC_ERROR);
      setState({ kind: "codes", codes: body.recoveryCodes });
    } catch {
      setState({ kind: "invalid" });
    }
  }

  return (
    <main className="activation-page">
      <header className="activation-header">
        <img className="activation-brand" src="/assets/brand/logo.jpeg" alt="Manita de Gato, salón de belleza" />
        <div><h1>Reemplazo de verificación en dos pasos</h1><p>Configura tu nuevo método de seguridad.</p></div>
      </header>
      <section className="activation-card" aria-labelledby="lost-factor-title">
        {state.kind === "loading" ? <p role="status">Comprobando el enlace…</p> : null}
        {state.kind === "invalid" ? <>
          <h2 id="lost-factor-title">No fue posible continuar</h2>
          <p className="activation-notice activation-notice--error" role="alert">{GENERIC_ERROR}</p>
          <a className="activation-exit" href="/admin/">Volver al inicio de sesión</a>
        </> : null}
        {state.kind === "ready" || state.kind === "submitting" ? <form className="activation-form activation-form--totp" onSubmit={(event) => void confirm(event)}>
          <h2 id="lost-factor-title">Configura tu nuevo factor</h2>
          <p className="activation-lead">Escanea el código QR con tu aplicación de autenticación y confirma el código de seis dígitos. Tu factor anterior seguirá activo hasta completar la confirmación.</p>
          <div className="activation-qr"><QRCodeSVG value={state.setup.provisioningUri} title="Código QR para configurar la verificación en dos pasos" /></div>
          <button className="activation-link-button" type="button" onClick={() => setShowManualKey((visible) => !visible)}>
            {showManualKey ? "Ocultar clave manual" : "No puedo escanear el código"}
          </button>
          {showManualKey ? <p className="totp-setup__manual-key" aria-label="Clave manual">{state.setup.manualKey}</p> : null}
          <label className="activation-field" htmlFor="lost-factor-code">Código de verificación
            <input id="lost-factor-code" type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" minLength={6} maxLength={6} required value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))} />
          </label>
          <button className="activation-button" type="submit" disabled={state.kind === "submitting" || code.length !== 6}>
            {state.kind === "submitting" ? "Confirmando…" : "Confirmar nuevo factor"}
          </button>
        </form> : null}
        {state.kind === "codes" ? <div className="activation-form">
          <h2 id="lost-factor-title">Guarda tus códigos de recuperación</h2>
          <p className="activation-notice">Se muestran una sola vez. Guárdalos ahora en un lugar seguro; no vuelvas a cargar esta página hasta hacerlo.</p>
          <ul className="activation-recovery-codes" aria-label="Códigos de recuperación">
            {state.codes.map((recoveryCode) => <li key={recoveryCode}><code>{recoveryCode}</code></li>)}
          </ul>
          <p className="activation-lead">Por seguridad, no se ha iniciado ninguna sesión. Vuelve al inicio e inicia sesión con tu nuevo factor.</p>
          <a className="activation-button activation-button--link" href="/admin/">Ir al inicio de sesión</a>
        </div> : null}
      </section>
    </main>
  );
}
