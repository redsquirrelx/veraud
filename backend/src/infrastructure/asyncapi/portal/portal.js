/* global AsyncApiStandalone, URL, window, document, fetch, MutationObserver */
const address = new URL("/ws", window.location.href)
address.protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
document.getElementById("ws-address").textContent = address.href

// The official renderer heads every operation with the shared channel address.
// Reuse its sidebar label so each section also has a distinct, matching title.
function showOperationTitles(root) {
  for (const link of root.querySelectorAll('a[href^="#operation-"]')) {
    const label = link.querySelector("span")?.textContent
    const section = document.getElementById(link.getAttribute("href").slice(1))
    const heading = section?.querySelector("h3")
    if (!label || !heading) continue
    let title = heading.querySelector(".portal-operation-title")
    if (!title) {
      title = document.createElement("span")
      title.className = "portal-operation-title"
      heading.append(title)
    }
    if (title.textContent !== label) title.textContent = label
  }
}

async function showDocumentation() {
  const status = document.getElementById("portal-status")
  try {
    const response = await fetch("/docs/ws/spec")
    if (!response.ok) throw new Error(`Specification request failed (${response.status})`)
    const schema = await response.text()
    const root = document.getElementById("asyncapi")
    const observer = new MutationObserver(() => showOperationTitles(root))
    observer.observe(root, { childList: true, subtree: true })
    AsyncApiStandalone.render({
      schema,
      config: { show: { sidebar: true } },
    }, root)
    showOperationTitles(root)
    status.hidden = true
  } catch (error) {
    status.textContent = `Could not load documentation: ${error.message}. Use the YAML download or reload the page.`
  }
}

void showDocumentation()
