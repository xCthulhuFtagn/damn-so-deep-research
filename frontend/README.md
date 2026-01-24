# Deep Research UI

This is the React-based frontend for the Deep Research agent.

## Prerequisites

- Node.js (v18 or higher recommended)
- npm (usually comes with Node.js)

## Project Requirements (`package.json`)

The list of dependencies is managed in `package.json`. The key libraries are:

- **Core**: `react`, `react-router-dom`
- **State**: `zustand`
- **Networking**: `axios`
- **Markdown & Formatting**:
  - `react-markdown`: Renders the chat messages.
  - `remark-gfm`: Adds support for tables, strikethrough, etc. (GitHub Flavored Markdown).
  - `@tailwindcss/typography`: Provides the `prose` classes for beautiful text styling.
- **Styling**: `tailwindcss`, `lucide-react` (icons)

## Setup & Installation

1. **Install Dependencies**
   Run this command to install all required packages defined in `package.json`:
   ```bash
   npm install
   ```

2. **Run Development Server**
   ```bash
   npm run dev
   ```
   The UI will typically be available at `http://localhost:5173`.

## Environment Variables

Create a `.env` file in this directory if you need to override defaults:

```env
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```
