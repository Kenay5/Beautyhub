import { FormEvent, ReactNode, useEffect, useState } from "react";

import { StaffInvitationPanel } from "./StaffInvitationPanel";
import { PasswordChangePanel } from "./PasswordChangePanel";
import { OwnEmailChangePanel } from "./OwnEmailChangePanel";
import { RecoveryCodeRegenerationPanel } from "./RecoveryCodeRegenerationPanel";
import { TotpReplacementPanel } from "./TotpReplacementPanel";
import { AdministrativeHistoryPanel } from "./AdministrativeHistoryPanel";
import {
  AdministrativeSession,
  AdministrativeSessionUnavailableError,
  closeAdministrativeSession,
  createAdministrativeSession,
  loadAdministrativeSession,
} from "./adminSessionClient";

type SessionState =
  | { kind: "loading" }
  | { kind: "unauthenticated"; message: string }
  | { kind: "unavailable"; message: string }
  | { kind: "recovery-codes"; codes: readonly string[] }
  | { kind: "authenticated"; session: AdministrativeSession };

export function AdminSessionGate() {
  const [state, setState] = useState<SessionState>({ kind: "loading" });

  function loadContext() {
    const controller = new AbortController();
    setState({ kind: "loading" });
    void loadAdministrativeSession(controller.signal)
      .then((session) => setState({ kind: "authenticated", session }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof AdministrativeSessionUnavailableError) {
          setState({
            kind: "unauthenticated",
            message: "Tu sesión no está disponible. Inicia sesión para continuar.",
          });
          return;
        }
        setState({
          kind: "unavailable",
          message: "No fue posible comprobar tu sesión. Inténtalo de nuevo.",
        });
      });
    return controller;
  }

  useEffect(() => {
    const controller = loadContext();
    return () => controller.abort();
  }, []);

  if (state.kind === "loading") {
    return <SessionMessage message="Comprobando tu sesión…" />;
  }
  if (state.kind === "unavailable") {
    return (
      <SessionMessage message={state.message}>
        <button type="button" onClick={() => loadContext()}>
          Reintentar
        </button>
      </SessionMessage>
    );
  }
  if (state.kind === "unauthenticated") {
    return (
      <AdministrativeLogin
        message={state.message}
        onAuthenticated={(session) =>
          setState({ kind: "authenticated", session })
        }
      />
    );
  }
  if (state.kind === "recovery-codes") {
    return (
      <RecoveryCodesDisplay
        codes={state.codes}
        onContinue={() =>
          setState({
            kind: "unauthenticated",
            message: "Tu sesión se cerró. Inicia sesión nuevamente.",
          })
        }
      />
    );
  }
  return (
    <AuthenticatedAdministration
      session={state.session}
      onPasswordChanged={() =>
        setState({
          kind: "unauthenticated",
          message: "Tu contraseña fue actualizada. Inicia sesión nuevamente.",
        })
      }
      onSessionUnavailable={() =>
        setState({
          kind: "unauthenticated",
          message: "Tu sesión terminó. Inicia sesión nuevamente.",
        })
      }
      onCodesRegenerated={(codes) => setState({ kind: "recovery-codes", codes })}
    />
  );
}

function AdministrativeLogin({
  message,
  onAuthenticated,
}: {
  message: string;
  onAuthenticated: (session: AdministrativeSession) => void;
}) {
  const [requestingRecovery, setRequestingRecovery] = useState(false);
  const [recoveryEmail, setRecoveryEmail] = useState("");
  const [recoveryMessage, setRecoveryMessage] = useState<string | null>(null);
  const [recoverySubmitting, setRecoverySubmitting] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [factor, setFactor] = useState<"totp" | "recovery">("totp");
  const [code, setCode] = useState("");
  const [feedback, setFeedback] = useState(message);
  const [loginFailed, setLoginFailed] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function requestPasswordRecovery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (recoverySubmitting) return;
    setRecoverySubmitting(true);
    try {
      const response = await fetch("/api/admin/password-recovery", {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: recoveryEmail }),
      });
      if (!response.ok) throw new Error("password recovery request is unavailable");
      const payload: unknown = await response.json();
      if (typeof payload !== "object" || payload === null || !("message" in payload) || typeof payload.message !== "string") {
        throw new Error("password recovery response is invalid");
      }
      setRecoveryMessage(payload.message);
    } catch {
      setRecoveryMessage("Si existe una cuenta activa con ese correo, recibirás instrucciones para recuperar tu contraseña.");
    } finally {
      setRecoveryEmail("");
      setRecoverySubmitting(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    try {
      await createAdministrativeSession({
        email,
        password,
        ...(factor === "totp" ? { totpCode: code } : { recoveryCode: code }),
      });
      onAuthenticated(await loadAdministrativeSession());
    } catch (error) {
      setLoginFailed(true);
      setFeedback(
        error instanceof AdministrativeSessionUnavailableError
          ? "Las credenciales no son válidas. Revisa los datos e inténtalo de nuevo."
          : "No fue posible iniciar sesión. Inténtalo de nuevo.",
      );
    } finally {
      setPassword("");
      setCode("");
      setSubmitting(false);
    }
  }

  return (
    <main className="admin-login-page">
      <header className="admin-login__brand">
        <img src="/assets/brand/logo.jpeg" alt="Manita de Gato, salón de belleza" />
      </header>
      {requestingRecovery ? (
        <section className="admin-login__card" aria-labelledby="password-recovery-request-title">
          <h1 id="password-recovery-request-title">Recuperar contraseña</h1>
          <p className="admin-login__subtitle">Solicita instrucciones para restablecer el acceso a tu cuenta.</p>
          {recoveryMessage ? <p className="admin-login__message admin-login__message--info" role="status">{recoveryMessage}</p> : null}
          <form className="admin-login__form" onSubmit={(event) => void requestPasswordRecovery(event)}>
            <label htmlFor="recovery-request-email">Correo</label>
            <input
              id="recovery-request-email"
              type="email"
              autoComplete="username"
              required
              maxLength={254}
              value={recoveryEmail}
              onChange={(event) => { setRecoveryEmail(event.target.value); setRecoveryMessage(null); }}
            />
            <button type="submit" disabled={recoverySubmitting}>
              {recoverySubmitting ? "Enviando…" : "Enviar instrucciones"}
            </button>
          </form>
          <button className="admin-login__secondary-action" type="button" onClick={() => { setRequestingRecovery(false); setRecoveryMessage(null); }}>
            Volver al inicio de sesión
          </button>
        </section>
      ) : (
      <section className="admin-login__card" aria-labelledby="admin-login-title">
        <h1 id="admin-login-title">Acceso administrativo</h1>
        <p className="admin-login__subtitle">Ingresa para gestionar el negocio</p>
        <h2 className="admin-login__visually-hidden">Iniciar sesión</h2>
        {feedback ? <p className={`admin-login__message${loginFailed ? " admin-login__message--error" : " admin-login__message--info"}`} role={loginFailed ? "alert" : "status"}>{feedback}</p> : null}
        <form className="admin-login__form" onSubmit={(event) => void submit(event)}>
          <label htmlFor="admin-email">Correo electrónico</label>
          <input
            id="admin-email"
            type="email"
            autoComplete="username"
            required
            maxLength={254}
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <label htmlFor="admin-password">Contraseña</label>
          <input
            id="admin-password"
            type="password"
            autoComplete="current-password"
            required
            minLength={1}
            maxLength={128}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <div className="admin-login__factor-heading">
            <label htmlFor="admin-factor-code">
              {factor === "totp" ? "Código de 6 dígitos" : "Código de recuperación"}
            </label>
            <span>Segundo factor</span>
          </div>
          <input
            id="admin-factor-code"
            type="text"
            inputMode={factor === "totp" ? "numeric" : "text"}
            autoComplete="one-time-code"
            required
            maxLength={factor === "totp" ? 32 : 64}
            value={code}
            onChange={(event) => setCode(event.target.value)}
          />
          <button className="admin-login__factor-toggle" type="button" onClick={() => { setFactor(factor === "totp" ? "recovery" : "totp"); setCode(""); }}>
            {factor === "totp" ? "Usar un código de recuperación" : "Usar código de verificación en su lugar"}
          </button>
          <button type="submit" disabled={submitting}>
            {submitting ? "Comprobando…" : "Iniciar sesión"}
          </button>
        </form>
        <div className="admin-login__recovery-divider" aria-hidden="true" />
        <button className="admin-login__recovery-link" type="button" onClick={() => { setRecoveryEmail(email); setRecoveryMessage(null); setRequestingRecovery(true); }}>
          ¿Olvidaste tu contraseña?
        </button>
      </section>
      )}
    </main>
  );
}

function AuthenticatedAdministration({
  session,
  onSessionUnavailable,
  onPasswordChanged,
  onCodesRegenerated,
}: {
  session: AdministrativeSession;
  onSessionUnavailable: () => void;
  onPasswordChanged: () => void;
  onCodesRegenerated: (codes: string[]) => void;
}) {
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<"security" | "history">("security");

  async function logout() {
    try {
      await closeAdministrativeSession(session.csrfToken);
      onSessionUnavailable();
    } catch (error) {
      if (error instanceof AdministrativeSessionUnavailableError) {
        onSessionUnavailable();
        return;
      }
      setLogoutError("No fue posible cerrar la sesión. Inténtalo de nuevo.");
    }
  }

  return (
    <>
      <header className="admin-session-bar" aria-label="Sesión administrativa">
        <p>
          Sesión activa: {session.role === "owner" ? "propietario" : "personal"}
        </p>
        <button type="button" onClick={() => void logout()}>
          Cerrar sesión
        </button>
      </header>
      {logoutError ? <p role="alert">{logoutError}</p> : null}
      {session.role === "owner" ? (
        <nav className="admin-area-navigation" aria-label="Secciones administrativas">
          <button
            type="button"
            aria-pressed={activeView === "security"}
            onClick={() => setActiveView("security")}
          >
            Mi seguridad
          </button>
          <button
            type="button"
            aria-pressed={activeView === "history"}
            onClick={() => setActiveView("history")}
          >
            Historial administrativo
          </button>
        </nav>
      ) : null}
      {session.role === "owner" && activeView === "history" ? (
        <AdministrativeHistoryPanel onSessionUnavailable={onSessionUnavailable} />
      ) : (
        <>
          {session.role === "owner" ? (
            <StaffInvitationPanel
              csrfToken={session.csrfToken}
              onSessionUnavailable={onSessionUnavailable}
            />
          ) : (
            <SessionMessage message="Tu sesión de personal está activa." />
          )}
          <div className="staff-access-page">
            <OwnEmailChangePanel
              csrfToken={session.csrfToken}
              onSessionUnavailable={onSessionUnavailable}
            />
            <PasswordChangePanel
              csrfToken={session.csrfToken}
              onSessionUnavailable={onSessionUnavailable}
              onPasswordChanged={onPasswordChanged}
            />
            <RecoveryCodeRegenerationPanel
              csrfToken={session.csrfToken}
              onSessionUnavailable={onSessionUnavailable}
              onRegenerated={onCodesRegenerated}
            />
            <TotpReplacementPanel
              csrfToken={session.csrfToken}
              onSessionUnavailable={onSessionUnavailable}
              onReplaced={onCodesRegenerated}
            />
          </div>
        </>
      )}
    </>
  );
}

function RecoveryCodesDisplay({
  codes,
  onContinue,
}: {
  codes: readonly string[];
  onContinue: () => void;
}) {
  return (
    <main className="staff-access-page">
      <section className="staff-access-card" aria-labelledby="recovery-codes-title">
        <h1 id="recovery-codes-title">Guarda tus nuevos códigos de recuperación</h1>
        <p>
          Estos códigos se mostrarán una sola vez. Guárdalos fuera de este dispositivo
          en un lugar seguro. Tu sesión ya se cerró.
        </p>
        <ul className="activation-recovery-codes" aria-label="Nuevos códigos de recuperación">
          {codes.map((code) => <li key={code}><code>{code}</code></li>)}
        </ul>
        <div className="activation-notice" role="note">
          Cada código funciona una sola vez. Los códigos anteriores ya no funcionan.
        </div>
        <button type="button" onClick={onContinue}>Ya guardé mis códigos</button>
      </section>
    </main>
  );
}

function SessionMessage({
  message,
  children,
}: {
  message: string;
  children?: ReactNode;
}) {
  return (
    <main className="staff-access-page">
      <section className="staff-access-card" aria-live="polite">
        <h1>Administración</h1>
        <p>{message}</p>
        {children}
      </section>
    </main>
  );
}
