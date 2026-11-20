/** Brand panel on the login and register pages (left column on wide screens). */
export function AuthHero() {
  return (
    <header className="auth-hero">
      <h1>DriveRadar</h1>
      <p className="auth-tagline">
        Every placement drive for your batch, <strong>filtered for you.</strong>
      </p>
      <ul className="auth-points">
        <li>See the drives you qualify for first, with reasons for the rest</li>
        <li>Deadline reminders on Telegram, 24 h and 3 h before</li>
        <li>Track each application from applied to offer</li>
      </ul>
    </header>
  );
}
