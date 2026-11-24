// dotrix.cc: what dotrix is, the team, how approvals work, and where to start (the cloud app, the
// desktop app, or the CLI). Everything here is something dotrix does today.
import {
  CommandIcon,
  ArrowLeftIcon,
  ArrowRightIcon,
  ArrowUpRightIcon,
  LibraryBigIcon,
  GlobeIcon,
  MessageCircleMoreIcon,
  CheckIcon,
  CodeIcon,
  GitPullRequestIcon,
  KeyIcon,
  TerminalIcon,
  LockKeyholeIcon,
  SearchIcon,
  ShieldCheckIcon,
  SquareTerminalIcon,
  AppWindowIcon,
} from "lucide-react";
import { useEffect, type ReactNode } from "react";

import { APP_URL, DOWNLOADS_URL } from "./config";
import { Face, Mark } from "./Face";

const SIGN_IN = `${APP_URL}/login`;
const SIGN_UP = `${APP_URL}/signup`;

const TEAM = [
  { name: "Nova", role: "Lead", c: "#E0A92E", text: "Plans the work, brings in the right agent, and pulls it together." },
  { name: "Lyra", role: "Product", c: "#3D9E6A", text: "Requirements, user stories, and acceptance criteria." },
  { name: "Orion", role: "Architecture", c: "#3B82C4", text: "Weighs the options and records the decisions." },
  { name: "Vega", role: "Research", c: "#5AA9D6", text: "Reads the web and your documents, with sources." },
  { name: "Juno", role: "Review", c: "#D0628B", text: "Checks work against the requirements, and reviews every PR." },
  { name: "Echo", role: "Documentation", c: "#8C6FD6", text: "Keeps your documents and the repo wiki current." },
  { name: "Kai", role: "Coding", c: "#5C95C4", text: "Writes the code in a sandbox and opens the pull request." },
];

const PROVIDERS = ["Anthropic", "OpenAI", "Google", "xAI", "DeepSeek", "Mistral", "Groq", "OpenRouter", "NVIDIA"];
const ENGINES = ["Claude Code", "Codex", "OpenCode", "fx"];

function Window({ src, alt, eager = false }: { src: string; alt: string; eager?: boolean }) {
  return (
    <div className="window">
      <div className="window-bar" aria-hidden="true">
        <i />
        <i />
        <i />
      </div>
      <img src={src} alt={alt} width={2400} height={1500} loading={eager ? "eager" : "lazy"} decoding="async" />
    </div>
  );
}

function Bullets({ items }: { items: ReactNode[] }) {
  return (
    <ul className="bullets">
      {items.map((item, i) => (
        <li key={i}>
          <CheckIcon size={16} />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function Section({ id, children, className = "" }: { id?: string; children: ReactNode; className?: string }) {
  return (
    <section id={id} className={`section ${className}`}>
      <div className="wrap reveal">{children}</div>
    </section>
  );
}

function Nav({ onHome = true }: { onHome?: boolean }) {
  const sec = (id: string) => (onHome ? `#${id}` : `/#${id}`);
  return (
    <header className="nav">
      <div className="wrap nav-in">
        <a href="/" className="brand" aria-label="dotrix home">
          <Mark />
          <span>dotrix</span>
        </a>
        <nav className="nav-links" aria-label="Sections">
          <a href={sec("team")}>Team</a>
          <a href={sec("approvals")}>Approvals</a>
          <a href={sec("keys")}>Your keys</a>
          <a href={sec("start")}>Getting started</a>
          <a href={sec("download")}>Download</a>
        </nav>
        <div className="nav-cta">
          <a href={SIGN_IN} className="btn btn-ghost">
            Sign in
          </a>
          <a href={SIGN_UP} className="btn btn-primary btn-sm">
            Get started
          </a>
        </div>
      </div>
    </header>
  );
}

const TILES = [
  { Icon: MessageCircleMoreIcon, cls: "t1" },
  { Icon: GitPullRequestIcon, cls: "t2" },
  { Icon: ShieldCheckIcon, cls: "t3" },
  { Icon: LibraryBigIcon, cls: "t4" },
  { Icon: SearchIcon, cls: "t5" },
  { Icon: CodeIcon, cls: "t6" },
];

function Hero() {
  return (
    <section className="hero">
      <div className="hero-grid" aria-hidden="true" />
      <div className="tiles" aria-hidden="true">
        {TILES.map(({ Icon, cls }) => (
          <span key={cls} className={`tile ${cls}`}>
            <Icon size={28} />
          </span>
        ))}
      </div>
      <div className="wrap hero-in">
        <a href="#download" className="pill">
          <span className="pill-dot" />
          Desktop and CLI for Windows are here
          <ArrowRightIcon size={13} />
        </a>
        <h1>
          Plan, build and ship
          <br />
          <span className="serif">with a team of agents.</span>
        </h1>
        <p className="lead">
          Nova and five specialists plan, research and review with you. Kai writes the code and opens the pull request. Nothing changes without your approval.
        </p>
        <div className="cta-row">
          <a href={SIGN_UP} className="btn btn-primary btn-lg">
            Open dotrix
            <ArrowRightIcon size={16} />
          </a>
          <a href={DOWNLOADS_URL} className="btn btn-secondary btn-lg">
            <AppWindowIcon size={17} />
            Download for Windows
          </a>
        </div>
        <p className="fine">Bring your own model keys · macOS and Linux soon</p>
      </div>
      <div className="wrap hero-shot">
        <div className="glow" aria-hidden="true" />
        <div className="shot-desktop">
          <Window src="/shots/home.webp" alt="dotrix Home: your tasks, decisions waiting on you, and what each agent is doing" eager />
        </div>
        <div className="shot-phone">
          <img src="/shots/phone-home.webp" alt="dotrix Home on a phone" width={780} height={1688} loading="eager" />
        </div>
      </div>
    </section>
  );
}

function Team() {
  return (
    <Section id="team">
      <div className="head">
        <h2>
          Meet the team. <span className="serif dim">Seven agents, one lead.</span>
        </h2>
        <p className="sub">You talk to Nova. Nova brings in the specialist the work needs, and Kai takes the build when you ask for one.</p>
      </div>
      <div className="team">
        {TEAM.map((agent) => (
          <article key={agent.name} className="agent" style={{ ["--c" as string]: agent.c }}>
            <Face c={agent.c} size={44} />
            <div>
              <h3>
                {agent.name} <span>{agent.role}</span>
              </h3>
              <p>{agent.text}</p>
            </div>
          </article>
        ))}
      </div>
    </Section>
  );
}

function ApprovalCard() {
  const files = [
    ["src/components/Hero.tsx", "+142", "−8"],
    ["src/components/Hero.test.tsx", "+64", "−0"],
    ["src/styles/hero.css", "+38", "−12"],
  ];
  return (
    <div className="mock">
      <div className="mock-h">
        <Face c="#5C95C4" size={26} />
        <div>
          <b>Kai</b> <span className="muted">· WEB-139 Build hero component</span>
        </div>
        <span className="badge">Changes ready</span>
      </div>
      <div className="mock-branch mono">dotrix/web-139-build-hero → main · 3 files · checks passed</div>
      <div className="mock-files">
        {files.map(([path, plus, minus]) => (
          <div key={path} className="mock-file mono">
            <span>{path}</span>
            <span className="plus">{plus}</span>
            <span className="minus">{minus}</span>
          </div>
        ))}
      </div>
      <div className="mock-f">
        <span className="muted">Nothing is pushed until someone accepts.</span>
        <span className="grow" />
        <button type="button" className="btn btn-ghost btn-sm" tabIndex={-1}>
          Discard
        </button>
        <button type="button" className="btn btn-light btn-sm" tabIndex={-1}>
          <CheckIcon size={14} />
          Accept and push
        </button>
      </div>
    </div>
  );
}

function Approvals() {
  return (
    <Section id="approvals">
      <div className="split">
        <div className="split-visual">
          <ApprovalCard />
          <div className="connector" aria-hidden="true" />
          <div className="chip">
            <GitPullRequestIcon size={16} />
            Pull request opened · Juno is reviewing
          </div>
        </div>
        <div className="split-text">
          <h2>
            Every change <span className="serif">waits for you.</span>
          </h2>
          <p className="sub">
            Agents propose; people decide. Pick how much to approve by hand, from every change to only what matters. Owners set the limit for everyone.
          </p>
          <Bullets
            items={[
              <>
                <b>Manual, Accept edits, or Auto</b>, the same for chat and code
              </>,
              <>Kai works on a branch; the PR stays your review point</>,
              <>Juno reviews every PR and reads failed CI for you</>,
              <>Every write is in the audit log, with who approved it</>,
            ]}
          />
        </div>
      </div>
    </Section>
  );
}

function Inbox() {
  return (
    <Section>
      <div className="split reverse">
        <div className="split-text">
          <h2>
            Decide from <span className="serif">one inbox.</span>
          </h2>
          <p className="sub">
            Approvals, plans and questions from every project come to you in one place. Approve Kai's turn, accept a change, or open the conversation.
          </p>
          <Bullets
            items={[
              "Approve or reject a coding turn in a click",
              "Mentions, assignments and due dates beside them",
              "By email as they happen, or as a daily digest",
            ]}
          />
        </div>
        <div className="split-visual">
          <Window src="/shots/inbox.webp" alt="The dotrix Inbox, with Kai waiting for approval to start coding" />
        </div>
      </div>
    </Section>
  );
}

function Keys() {
  return (
    <Section id="keys">
      <div className="head">
        <h2>
          Bring your own keys. <span className="serif dim">Keep your plan.</span>
        </h2>
        <p className="sub">
          dotrix doesn't resell tokens. Each person connects their own provider key, encrypted at rest, and picks the model for each agent. Kai codes with the
          engine that fits the model.
        </p>
      </div>
      <div className="providers">
        {PROVIDERS.map((name) => (
          <div key={name} className="provider">
            <KeyIcon size={18} />
            <span>{name}</span>
          </div>
        ))}
      </div>
      <div className="engines">
        <span className="muted">Kai codes with</span>
        {ENGINES.map((name) => (
          <span key={name} className="engine mono">
            {name}
          </span>
        ))}
      </div>
      <div className="facts">
        {["No markup on tokens", "Keys encrypted, never shared", "A model per agent", "Sandboxes reach only the model API"].map((fact) => (
          <span key={fact}>
            <CheckIcon size={14} />
            {fact}
          </span>
        ))}
      </div>
    </Section>
  );
}

function Knowledge() {
  return (
    <Section>
      <div className="split">
        <div className="split-visual">
          <Window src="/shots/knowledge.webp" alt="A project's knowledge in dotrix: documents, decisions and research" />
        </div>
        <div className="split-text">
          <h2>
            Knowledge that <span className="serif">stays current.</span>
          </h2>
          <p className="sub">
            Requirements, decisions and research live with the project, versioned. Every agent reads them before it acts, as evidence, never as orders.
          </p>
          <Bullets
            items={[
              "Upload documents; they become searchable Markdown",
              "Echo writes a cited wiki of your repository",
              "A push that outdates a page tells you which one",
            ]}
          />
        </div>
      </div>
    </Section>
  );
}

function Board() {
  return (
    <Section>
      <div className="head center">
        <h2>
          Your board, <span className="serif">with agents on it.</span>
        </h2>
        <p className="sub">Issues, epics and checklists your team already knows. Assign one to Kai, or ask Nova about it from the project.</p>
      </div>
      <div className="pair">
        <Window src="/shots/board.webp" alt="A dotrix project board" />
        <Window src="/shots/overview.webp" alt="A dotrix project overview with progress and milestones" />
      </div>
    </Section>
  );
}

function Terminal() {
  return (
    <Section>
      <div className="split">
        <div className="split-visual">
          <div className="term">
            <div className="term-bar">
              <i />
              <i />
              <i />
              <span className="mono">~/acme-web</span>
            </div>
            <pre className="mono">
              <span className="p">$</span> dotrix login{"\n"}
              <span className="ok">✓</span> <span className="dim">Signed in as tanjim@acme.dev</span>
              {"\n"}
              <span className="p">$</span> dotrix link{"\n"}
              <span className="ok">✓</span> <span className="dim">Linked to Website Redesign (WEB)</span>
              {"\n"}
              <span className="p">$</span> dotrix code WEB-139{"\n"}
              <span className="dim">▲ Kai is coding on this computer…</span>
              {"\n"}
              <span className="ok">✓</span> <span className="dim">3 files changed · changes ready to accept</span>
              {"\n"}
              <span className="p">$</span> <span className="caret" />
            </pre>
          </div>
        </div>
        <div className="split-text">
          <h2>
            Or stay in <span className="serif">your terminal.</span>
          </h2>
          <p className="sub">
            The CLI links a checkout to its project. Run Kai's turns on your own machine, chat with Nova, or work the board, all through the same approvals.
          </p>
          <Bullets
            items={[
              <>
                <span className="mono">dotrix runner</span> codes your local turns
              </>,
              "An MCP server for Claude Code and Codex",
              "The desktop app bundles it for you",
            ]}
          />
        </div>
      </div>
    </Section>
  );
}

const STEPS: { title: string; text: ReactNode }[] = [
  {
    title: "Create your account",
    text: (
      <>
        Sign up with your email (you'll get a link to verify it) or with GitHub. You land in your own private workspace, and onboarding walks you through the
        rest.
      </>
    ),
  },
  {
    title: "Connect your model key",
    text: (
      <>
        In <b>Account → Your models</b>, add a key from Anthropic, OpenAI, Google, or another supported provider. It's encrypted, it's only ever used for your
        own runs, and your agents can't run without one. Projects and tasks work without a key.
      </>
    ),
  },
  {
    title: "Start a project",
    text: (
      <>
        Explore an idea, start a new codebase, or connect a repository you have. To work on code, install the dotrix GitHub App when onboarding asks, and pick
        the repository.
      </>
    ),
  },
  {
    title: "Decide what needs you",
    text: (
      <>
        <b>Manual</b> asks you before every change, with the diff. <b>Accept edits</b> lets through what you asked for, and <b>Auto</b> goes further. Changes to
        files your CI runs always wait for you, and you merge every pull request yourself.
      </>
    ),
  },
  {
    title: "Stop anything",
    text: (
      <>
        <b>Stop</b> ends a reply in Chat or a coding turn in Code. A stopped, rejected or interrupted run shows exactly that, never a success or a pull request
        it didn't make.
      </>
    ),
  },
  {
    title: "Tell us what broke",
    text: (
      <>
        <b>Help &amp; resources → Report a problem</b> opens an issue on GitHub. Issues are public, so describe what happened without keys, private code or
        anything you wrote in dotrix.
      </>
    ),
  },
];

function GettingStarted() {
  return (
    <Section id="start">
      <div className="head">
        <h2>
          Getting started. <span className="serif dim">Six steps, a few minutes.</span>
        </h2>
        <p className="sub">The private beta is for solo developers: one personal workspace, your own key, and your own GitHub.</p>
      </div>
      <ol className="steps">
        {STEPS.map((step, i) => (
          <li key={step.title} className="step">
            <span className="step-n mono">{i + 1}</span>
            <div>
              <h3>{step.title}</h3>
              <p>{step.text}</p>
            </div>
          </li>
        ))}
      </ol>
      <div className="facts">
        {["BYOK across 9 model providers", "Kai codes in a sandbox or on your computer", "Desktop app for Windows", "No team workspaces yet"].map((fact) => (
          <span key={fact}>
            <CheckIcon size={14} />
            {fact}
          </span>
        ))}
      </div>
    </Section>
  );
}

function Download() {
  return (
    <Section id="download">
      <div className="head center">
        <h2>
          Start where <span className="serif">you work.</span>
        </h2>
        <p className="sub">The web app, the desktop app and the CLI share one account, one board and the same approvals.</p>
      </div>
      <div className="downloads">
        <article className="dl">
          <GlobeIcon size={26} />
          <h3>Web</h3>
          <p>Everything in your browser. Coding runs in the cloud, in a sandbox.</p>
          <a href={SIGN_UP} className="btn btn-primary">
            Open dotrix
            <ArrowUpRightIcon size={15} />
          </a>
          <span className="soon">Nothing to install</span>
        </article>
        <article className="dl">
          <AppWindowIcon size={26} />
          <h3>Desktop</h3>
          <p>The app, with local coding on your own computer. Windows now.</p>
          <a href={DOWNLOADS_URL} className="btn btn-secondary">
            Download for Windows
          </a>
          <span className="soon">
            <CommandIcon size={14} /> macOS soon
          </span>
        </article>
        <article className="dl">
          <SquareTerminalIcon size={26} />
          <h3>CLI</h3>
          <p>Link a checkout, run Kai locally, and connect Claude Code or Codex.</p>
          <a href={DOWNLOADS_URL} className="btn btn-secondary">
            Download for Windows
          </a>
          <span className="soon">
            <TerminalIcon size={14} /> macOS and Linux soon
          </span>
        </article>
      </div>
    </Section>
  );
}

function Final() {
  return (
    <section className="final">
      <div className="final-glow" aria-hidden="true" />
      <div className="wrap reveal">
        <h2>
          Build with
          <br />
          <span className="serif">your agents.</span>
        </h2>
        <p className="sub">Start with a project, connect a repository, and ask Nova where to begin.</p>
        <div className="cta-row">
          <a href={SIGN_UP} className="btn btn-primary btn-lg">
            Get started
            <ArrowRightIcon size={16} />
          </a>
          <a href={SIGN_IN} className="btn btn-secondary btn-lg">
            Sign in
          </a>
        </div>
        <p className="fine">
          <LockKeyholeIcon size={13} /> Your conversations stay yours. Every change stays reviewable and auditable.
        </p>
      </div>
    </section>
  );
}

const LEGAL_UPDATED = "November 2026";
const ISSUES_NEW_URL = "https://github.com/adeyemiadekunle/dotrix/issues/new";

function LegalShell({ title, lead, children }: { title: string; lead: string; children: ReactNode }) {
  return (
    <article className="legal">
      <div className="wrap legal-in">
        <a href="/" className="legal-back">
          <ArrowLeftIcon size={15} />
          Back to dotrix
        </a>
        <header className="legal-head">
          <h1>{title}</h1>
          <p className="legal-lead">{lead}</p>
          <p className="legal-meta">Last updated {LEGAL_UPDATED}</p>
        </header>
        <div className="legal-body">{children}</div>
      </div>
    </article>
  );
}

function TermsPage() {
  return (
    <LegalShell title="Terms of Service" lead="How dotrix workspaces, connected model keys, repositories, and approval gates work when you use the service.">
      <section>
        <h2>1. Accounts and workspaces</h2>
        <p>
          You need an account to create or join a dotrix workspace. Keep your credentials secure and do not share sign-in links or API tokens. Workspace owners
          manage workspace membership, approval caps, and repository connections for their workspace.
        </p>
      </section>
      <section>
        <h2>2. Your model keys and third-party providers</h2>
        <p>
          dotrix uses a Bring Your Own Key (BYOK) model. You connect your own API keys from supported model providers (such as Anthropic, OpenAI, or Google) and
          pay those providers directly under their terms and pricing. dotrix does not resell tokens or add markup.
        </p>
      </section>
      <section>
        <h2>3. Code execution, approvals, and GitHub repositories</h2>
        <p>
          Coding runs only execute on repositories you connect or authorize through the dotrix GitHub App or local runner. Changes wait according to the
          conversation&apos;s approval setting (Manual, Accept edits, or Auto), CI workflow edits remain approval-gated, and human members decide whether to
          merge pull requests.
        </p>
      </section>
      <section>
        <h2>4. Ownership of your work</h2>
        <p>
          You retain all rights to your prompts, project documents, tasks, and code changes generated or reviewed inside your workspaces. You are responsible
          for reviewing agent output before merging or shipping it to production.
        </p>
      </section>
      <section>
        <h2>5. Acceptable use and beta availability</h2>
        <p>
          Do not use dotrix to abuse sandboxes, bypass access controls, or automate harm against third-party services. During beta, features and platform
          integrations evolve continuously and are provided on an as-available basis.
        </p>
      </section>
      <section>
        <h2>6. Questions or problem reports</h2>
        <p>
          If you spot an issue or have a question about these terms, open a public report on{" "}
          <a href={ISSUES_NEW_URL} target="_blank" rel="noreferrer">
            GitHub Issues
          </a>{" "}
          without including private keys or confidential workspace content.
        </p>
      </section>
    </LegalShell>
  );
}

function PrivacyPage() {
  return (
    <LegalShell title="Privacy Policy" lead="What stays private to you, how connected provider keys and code sandboxes are isolated, and what we store.">
      <section>
        <h2>1. Private conversations vs. shared workspace items</h2>
        <p>
          Your individual chat threads with Nova and coding agent transcripts remain private to your account unless you explicitly publish an outcome, document,
          or pull request metadata to your shared project.
        </p>
      </section>
      <section>
        <h2>2. Provider API keys and credentials</h2>
        <p>
          Personal model API keys are encrypted at rest and never shared with other workspace members. Cloud coding sandboxes and isolated local namespaces only
          receive strictly scoped model access needed to run your authorized turn.
        </p>
      </section>
      <section>
        <h2>3. Code and execution environments</h2>
        <p>
          When Kai runs in a cloud sandbox or locally through the desktop app or CLI runner, dotrix accesses only the workspace repository you selected and
          records session summaries, changed files, commands, and audit events needed to review and recover runs.
        </p>
      </section>
      <section>
        <h2>4. Cookies and local storage</h2>
        <p>
          dotrix uses essential session cookies and browser storage for authentication state, theme preferences, and pane layout state. Embedded browser-pane
          sessions keep cookies local to the desktop app settings you control.
        </p>
      </section>
      <section>
        <h2>5. Retention and control</h2>
        <p>
          You can remove connected API keys, disconnect GitHub installations, or delete sessions inside dotrix settings at any time. Public bug reports
          submitted via{" "}
          <a href={ISSUES_NEW_URL} target="_blank" rel="noreferrer">
            GitHub Issues
          </a>{" "}
          are public—never paste API keys or private code into them.
        </p>
      </section>
    </LegalShell>
  );
}

function Footer({ onHome = true, route = "/" }: { onHome?: boolean; route?: string }) {
  return (
    <footer className="footer">
      <div className="wrap footer-in">
        <a href="/" className="brand" aria-label="dotrix home">
          <Mark size={18} />
          <span>dotrix</span>
        </a>
        <span className="muted">© 2026 dotrix</span>
        <span className="grow" />
        <nav aria-label="Footer">
          <a href={SIGN_IN}>Sign in</a>
          <a href={SIGN_UP}>Sign up</a>
          <a href={onHome ? "#start" : "/#start"}>Getting started</a>
          <a href={DOWNLOADS_URL}>Download</a>
          <a href="/terms" aria-current={route === "/terms" ? "page" : undefined}>
            Terms
          </a>
          <a href="/privacy" aria-current={route === "/privacy" ? "page" : undefined}>
            Privacy
          </a>
        </nav>
      </div>
    </footer>
  );
}

export function App({ pathname = "/" }: { pathname?: string }) {
  const route = pathname.replace(/\/+$/, "") || "/";
  const onHome = route === "/";
  useEffect(() => {
    const els = Array.from(document.querySelectorAll<HTMLElement>(".reveal"));
    if (!els.length) return;
    if (!("IntersectionObserver" in window) || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      els.forEach((el) => el.classList.add("in"));
      return;
    }
    const seen = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("in");
            seen.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.01, rootMargin: "0px 0px -4% 0px" },
    );
    for (const el of els) {
      const rect = el.getBoundingClientRect();
      if (rect.top < window.innerHeight) {
        el.classList.add("in");
      } else {
        seen.observe(el);
      }
    }
    return () => seen.disconnect();
  }, [route]);
  return (
    <>
      <Nav onHome={onHome} />
      <main>
        {route === "/terms" ? (
          <TermsPage />
        ) : route === "/privacy" ? (
          <PrivacyPage />
        ) : (
          <>
            <Hero />
            <Team />
            <Approvals />
            <Inbox />
            <Keys />
            <Knowledge />
            <Board />
            <Terminal />
            <GettingStarted />
            <Download />
            <Final />
          </>
        )}
      </main>
      <Footer onHome={onHome} route={route} />
    </>
  );
}
