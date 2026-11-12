# Getting started with the dotrix beta

The private beta is for solo developers: one personal workspace, your own model key, and your own
GitHub. This page is the long form of [dotrix.cc/#start](https://dotrix.cc/#start), which the app
links to from **Help & resources → Getting started**.

## 1. Create your account

Sign up at the app with your email (you'll get a link to verify it) or with GitHub. You land in your
own private workspace, and onboarding walks you through a project, GitHub and your model.

Forgot your password? **Forgot password** on the sign-in page emails a reset link, and **Email me a
sign-in link** signs you in without one. Settings → Sessions lists where you're signed in and signs
out any of them.

## 2. Connect your model key

Open **Account → Your models** and add a key from **Anthropic**, **OpenAI** or **Google**.

- Your key is encrypted, and only ever used for runs you start. dotrix doesn't resell tokens and has
  no key of its own to fall back on, so agents don't run until you add one.
- Projects, tasks and documents all work without a key.
- Pick your default model there too. Each conversation and coding session can use a different one.
- When a provider stops a run at its limit, the run says so and **Continue** picks it up from where it
  stopped, now or once the limit resets.

## 3. Start a project

Onboarding offers three starting points:

- **Explore an idea:** a draft project with no repository, dates or finished plan.
- **Start a new codebase:** say what you're building, then create its repository on GitHub.
- **Connect an existing repository:** dotrix takes an inventory of it, and Echo can explain it in a
  wiki you review.

To work on code, install the **dotrix GitHub App** when onboarding asks and pick the repository. Kai
never holds a GitHub token, never pushes to your default branch, and opens a pull request for you to
merge.

## 4. Talk to Nova, and hand building to Kai

Chat is where you talk to **Nova**, who brings in Lyra (product), Orion (architecture), Vega
(research), Juno (review) and Echo (documentation) when the work needs them. Each message has a
mode:

- **Discuss** to think things through, **Plan** to save a plan, **Build** to hand it to Kai,
  **Review** to look at what Kai did.

**Kai** codes in **Codes**, below Chat: in a cloud sandbox, or on your own computer with the desktop
app (Windows). Each session has its own branch and pull request. Juno reviews the pull request on
GitHub, and when CI fails, Juno reads the logs and **Ask Kai to fix** starts a follow-up.

## 5. Decide what needs you

The approval mode is picked in the message box:

- **Manual:** every change waits for you, with its diff. Kai's turns wait to start, and again before
  they're pushed.
- **Accept edits:** what you asked for goes through, recorded as approved by you.
- **Auto:** goes further, and checkpoints don't pause.

Whatever the mode, changes to files your CI runs wait for you, Nova's first hand-off to Kai waits in
your Inbox unless you're in Auto, and **you merge every pull request yourself**. A pushed turn can be
reverted from Codes.

## 6. Stop anything

**Stop** ends a reply in Chat or a coding turn in Codes, and cancels anything you queued. A stopped,
rejected or interrupted run shows exactly that: dotrix never reports a success or a pull request that
didn't happen. A coding turn cut off by a restart is checked against GitHub and either adopted, run
again, or left for you under **Check and recover**.

## 7. Tell us what broke

**Help & resources → Report a problem** opens a new issue on GitHub. Issues are **public**, so
describe what happened without keys, private code, or anything you wrote in dotrix.

## What the beta supports

| | |
| --- | --- |
| Workspace | One personal workspace. Team workspaces are off for the beta. |
| Chat models | Your own key from Anthropic, OpenAI or Google |
| Coding | Kai in a cloud sandbox, or on your Windows computer with the desktop app |
| Storage | 1 GB of uploads (documents and task attachments) per workspace; Settings → Workspace shows the use |
| Desktop app | Windows, unsigned for now (Windows SmartScreen warns the first time) |

The full list of what's supported, checked and still open is in
[solo-beta-readiness.md](solo-beta-readiness.md).
