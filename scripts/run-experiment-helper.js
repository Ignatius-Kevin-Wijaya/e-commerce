#!/usr/bin/env node

const fs = require("fs");

function usage() {
  console.error(
    "Usage: run-experiment-helper.js <print-configmaps|clone-job|urlencode|filter-events|" +
      "clone-job-env|pod-snapshot|hpa-snapshot|shuffle-plan|render-deployment|configmap-from-file|configmap-from-files> ..."
  );
  process.exit(1);
}

function splitYamlDocs(content) {
  return content
    .split(/^---\s*$/m)
    .map((doc) => doc.trim())
    .filter(Boolean);
}

function printDocs(docs) {
  if (!docs.length) {
    return;
  }
  process.stdout.write(docs.map((doc) => `---\n${doc}\n`).join(""));
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function replaceEnvValue(doc, name, value) {
  const pattern = new RegExp(
    `(- name: ${escapeRegExp(name)}\\s*\\n\\s*value:\\s*)\"[^\"]*\"`,
    "m"
  );
  return doc.replace(pattern, `$1"${String(value)}"`);
}

function commandPrintConfigmaps(yamlFile) {
  const docs = splitYamlDocs(fs.readFileSync(yamlFile, "utf8")).filter((doc) =>
    /\nkind:\s*ConfigMap\s*(?:\n|$)/.test(`\n${doc}\n`)
  );
  printDocs(docs);
}

function commandCloneJob(yamlFile, templateName, newName, service) {
  const docs = splitYamlDocs(fs.readFileSync(yamlFile, "utf8"));
  let jobDoc = docs.find(
    (doc) => doc.includes("kind: Job") && doc.includes(`name: ${templateName}`)
  );

  if (!jobDoc) {
    console.error(`ERROR: Job template '${templateName}' not found in ${yamlFile}`);
    process.exit(1);
  }

  jobDoc = jobDoc.replace(
    new RegExp(`(^\\s*name:\\s*)${escapeRegExp(templateName)}$`, "m"),
    `$1${newName}`
  );

  const replacementsByService = {
    "product-service": {
      BASE_RPS: process.env.PRODUCT_BASE_RPS,
      PEAK_RPS: process.env.PRODUCT_PEAK_RPS,
      PRODUCT_PAGE_SIZE: process.env.PRODUCT_PAGE_SIZE,
      PRODUCT_MAX_PAGE: process.env.PRODUCT_MAX_PAGE,
      PRODUCT_SEARCH_TERMS: process.env.PRODUCT_SEARCH_TERMS,
    },
    "shipping-rate-service": {
      BASE_VUS: process.env.SHIPPING_BASE_VUS,
      PEAK_VUS: process.env.SHIPPING_PEAK_VUS,
      SHIPPING_MAX_ITEMS: process.env.SHIPPING_MAX_ITEMS,
      SHIPPING_MIN_WEIGHT_GRAMS: process.env.SHIPPING_MIN_WEIGHT_GRAMS,
      SHIPPING_MAX_WEIGHT_GRAMS: process.env.SHIPPING_MAX_WEIGHT_GRAMS,
      SHIPPING_DESTINATION_ZONES: process.env.SHIPPING_DESTINATION_ZONES,
    },
    "auth-service": {
      BASE_VUS: process.env.AUTH_BASE_VUS,
      PEAK_VUS: process.env.AUTH_PEAK_VUS,
      AUTH_ME_PERCENT: process.env.AUTH_ME_PERCENT,
      AUTH_LOGIN_PERCENT: process.env.AUTH_LOGIN_PERCENT,
      NUM_TEST_USERS: process.env.NUM_TEST_USERS,
    },
  };

  const replacements = replacementsByService[service] || {};
  for (const [name, value] of Object.entries(replacements)) {
    if (typeof value !== "undefined" && value !== "") {
      jobDoc = replaceEnvValue(jobDoc, name, value);
    }
  }

  printDocs([jobDoc]);
}

function commandUrlencode(query) {
  process.stdout.write(`${encodeURIComponent(query)}\n`);
}

function parseEventEpoch(event) {
  const candidates = [
    event.eventTime,
    event.series && event.series.lastObservedTime,
    event.lastTimestamp,
    event.firstTimestamp,
    event.metadata && event.metadata.creationTimestamp,
  ];

  for (const raw of candidates) {
    if (!raw) {
      continue;
    }
    const parsed = Date.parse(raw);
    if (!Number.isNaN(parsed)) {
      return parsed / 1000;
    }
  }
  return null;
}

function commandFilterEvents(service, jobName, hpaName, scaledobjectName, runStartEpoch) {
  const payload = JSON.parse(fs.readFileSync(0, "utf8"));
  const names = [service, jobName, hpaName, scaledobjectName].filter(Boolean);
  const threshold = Number(runStartEpoch) - 30;

  const filtered = (payload.items || [])
    .map((event) => [parseEventEpoch(event), event])
    .filter(([epoch, event]) => {
      if (epoch === null || epoch < threshold) {
        return false;
      }
      const objectName = (((event || {}).involvedObject || {}).name || "").toString();
      const message = (event.message || "").toString();
      return names.some((name) => name && (objectName.includes(name) || message.includes(name)));
    })
    .sort((a, b) => a[0] - b[0]);

  process.stdout.write("TIMESTAMP\tTYPE\tREASON\tOBJECT\tMESSAGE\n");
  for (const [epoch, event] of filtered) {
    const obj = event.involvedObject || {};
    const objectRef = `${(obj.kind || "").toLowerCase()}/${obj.name || ""}`.replace(/^\/+|\/+$/g, "");
    const message = (event.message || "").replace(/\t/g, " ").replace(/\n/g, " ");
    const timestamp = new Date(epoch * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");
    process.stdout.write(
      [timestamp, event.type || "", event.reason || "", objectRef, message].join("\t") + "\n"
    );
  }
}

// ── Open-loop pilot commands (scripts/run-pilot-openloop.sh) ────────────────

// Clone a suspended Job template, un-suspend it and set arbitrary env values.
// Every KEY must already exist in the template, so a typo fails loudly instead
// of silently running with the template default.
function commandCloneJobEnv(yamlFile, templateName, newName, rest) {
  const docs = splitYamlDocs(fs.readFileSync(yamlFile, "utf8"));
  let jobDoc = docs.find(
    (doc) => doc.includes("kind: Job") && new RegExp(`^\\s*name:\\s*${escapeRegExp(templateName)}$`, "m").test(doc)
  );
  if (!jobDoc) {
    console.error(`ERROR: Job template '${templateName}' not found in ${yamlFile}`);
    process.exit(1);
  }

  jobDoc = jobDoc.replace(
    new RegExp(`(^\\s*name:\\s*)${escapeRegExp(templateName)}$`, "m"),
    `$1${newName}`
  );
  jobDoc = jobDoc.replace(/^(\s*)suspend:\s*true\s*$/m, "$1suspend: false");

  for (const arg of rest) {
    if (arg.startsWith("--resources=")) {
      const [reqCpu, reqMem, limCpu, limMem] = arg.slice("--resources=".length).split(",");
      jobDoc = jobDoc.replace(
        /(requests:\s*\n\s*cpu:\s*)"[^"]*"(\s*\n\s*memory:\s*)"[^"]*"/m,
        `$1"${reqCpu}"$2"${reqMem}"`
      );
      jobDoc = jobDoc.replace(
        /(limits:\s*\n\s*cpu:\s*)"[^"]*"(\s*\n\s*memory:\s*)"[^"]*"/m,
        `$1"${limCpu}"$2"${limMem}"`
      );
      continue;
    }
    const eq = arg.indexOf("=");
    if (eq <= 0) {
      console.error(`ERROR: expected KEY=VALUE, got '${arg}'`);
      process.exit(1);
    }
    const name = arg.slice(0, eq);
    const value = arg.slice(eq + 1);
    const before = jobDoc;
    jobDoc = replaceEnvValue(jobDoc, name, value);
    if (jobDoc === before && !new RegExp(`- name: ${escapeRegExp(name)}\\s*\\n\\s*value:\\s*"${escapeRegExp(value)}"`).test(jobDoc)) {
      console.error(`ERROR: env '${name}' not found in Job template '${templateName}'`);
      process.exit(1);
    }
  }

  printDocs([jobDoc]);
}

function readinessOf(pod) {
  const cond = ((pod.status || {}).conditions || []).find((c) => c.type === "Ready");
  return cond ? { ready: cond.status === "True", since: cond.lastTransitionTime || null } : { ready: false, since: null };
}

// One compact JSON line per poll: every pod of the service with its Ready
// state and the exact Ready transition time (1 s resolution, from the API).
function commandPodSnapshot() {
  const payload = JSON.parse(fs.readFileSync(0, "utf8"));
  const pods = (payload.items || []).map((pod) => {
    const r = readinessOf(pod);
    return {
      name: pod.metadata.name,
      created: pod.metadata.creationTimestamp || null,
      deleting: pod.metadata.deletionTimestamp || null,
      phase: (pod.status || {}).phase || null,
      node: (pod.spec || {}).nodeName || null,
      ready: r.ready,
      ready_since: r.since,
    };
  });
  process.stdout.write(JSON.stringify({ ts: Date.now() / 1000, pods }) + "\n");
}

function commandHpaSnapshot() {
  const payload = JSON.parse(fs.readFileSync(0, "utf8"));
  const hpas = (payload.items || []).map((hpa) => {
    const status = hpa.status || {};
    return {
      name: hpa.metadata.name,
      current: status.currentReplicas,
      desired: status.desiredReplicas,
      last_scale: status.lastScaleTime || null,
      metrics: status.currentMetrics || [],
      conditions: (status.conditions || []).map((c) => ({ type: c.type, status: c.status, reason: c.reason })),
    };
  });
  process.stdout.write(JSON.stringify({ ts: Date.now() / 1000, hpas }) + "\n");
}

// Deterministic shuffle of the run list WITHIN each repetition block. Lines are
// "service config pattern rep"; blocks are ordered by rep, runs shuffled with a
// seeded PRNG so the plan is reproducible and stable across --resume.
function commandShufflePlan(runlistFile, seedText) {
  const runs = fs
    .readFileSync(runlistFile, "utf8")
    .split(/\r?\n/)
    .map((line) => line.replace(/#.*/, "").trim())
    .filter(Boolean)
    .map((line) => {
      const [service, config, pattern, rep] = line.split(/\s+/);
      if (!service || !config || !pattern || !/^\d+$/.test(rep || "")) {
        console.error(`ERROR: bad run-list line '${line}' (want: service config pattern rep)`);
        process.exit(1);
      }
      return { service, config, pattern, rep: Number(rep) };
    });

  let state = Number(seedText) >>> 0;
  const random = () => {
    // mulberry32
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };

  const reps = [...new Set(runs.map((r) => r.rep))].sort((a, b) => a - b);
  for (const rep of reps) {
    const block = runs.filter((r) => r.rep === rep);
    for (let i = block.length - 1; i > 0; i--) {
      const j = Math.floor(random() * (i + 1));
      [block[i], block[j]] = [block[j], block[i]];
    }
    for (const r of block) {
      process.stdout.write(`${r.service}|${r.config}|${r.pattern}|${r.rep}\n`);
    }
  }
}

// Render an experiment Deployment manifest (b1/b2) for the open-loop campaign:
// optionally swap the service image tag, mount files from a ConfigMap over the
// image (--volume-cm=NAME plus --mount=KEY:/path, repeated) and add env vars.
// Everything else (replicas, resources, probes) stays exactly as in the file.
function commandRenderDeployment(yamlFile, imageTag, rest) {
  let text = fs.readFileSync(yamlFile, "utf8");
  if (imageTag) {
    const before = text;
    text = text.replace(/^(\s*image:\s*\S+?):[\w.-]+\s*$/m, `$1:${imageTag}`);
    if (text === before) {
      console.error(`ERROR: no image line to retag in ${yamlFile}`);
      process.exit(1);
    }
  }
  const envMatch = text.match(/^(\s*)env:\s*$/m);
  if (rest.length && !envMatch) {
    console.error(`ERROR: no container env list in ${yamlFile}`);
    process.exit(1);
  }

  const volumeCm = (rest.find((a) => a.startsWith("--volume-cm=")) || "").slice("--volume-cm=".length);
  const mounts = rest.filter((a) => a.startsWith("--mount=")).map((a) => a.slice("--mount=".length).split(":"));
  rest = rest.filter((a) => !a.startsWith("--volume-cm=") && !a.startsWith("--mount="));
  if (mounts.length) {
    const containers = text.match(/^(\s*)containers:\s*$/m);
    if (!volumeCm || !containers || /^\s*(volumes|volumeMounts):\s*$/m.test(text)) {
      console.error(`ERROR: cannot add overlay mounts to ${yamlFile} (needs --volume-cm and no existing volumes)`);
      process.exit(1);
    }
    const c = envMatch[1];
    const mountLines = [`${c}volumeMounts:`];
    for (const [key, path] of mounts) {
      if (!key || !path) {
        console.error("ERROR: --mount expects KEY:/absolute/path");
        process.exit(1);
      }
      mountLines.push(`${c}  - name: openloop-overlay`, `${c}    mountPath: ${path}`, `${c}    subPath: ${key}`, `${c}    readOnly: true`);
    }
    // volumeMounts goes next to env (container level), volumes next to containers (pod level).
    text = text.replace(/^(\s*)env:\s*$/m, (line) => `${mountLines.join("\n")}\n${line}`);
    const p = containers[1];
    const volumeLines = [`${p}volumes:`, `${p}  - name: openloop-overlay`, `${p}    configMap:`, `${p}      name: ${volumeCm}`];
    text = text.replace(/^(\s*)containers:\s*$/m, (line) => `${volumeLines.join("\n")}\n${line}`);
  }

  const extra = [];
  for (const arg of rest) {
    const eq = arg.indexOf("=");
    if (eq <= 0) {
      console.error(`ERROR: expected KEY=VALUE, got '${arg}'`);
      process.exit(1);
    }
    const name = arg.slice(0, eq);
    if (new RegExp(`- name: ${escapeRegExp(name)}\\s*$`, "m").test(text)) {
      console.error(`ERROR: env '${name}' already present in ${yamlFile}`);
      process.exit(1);
    }
    const indent = envMatch[1];
    extra.push(`${indent}  - name: ${name}`, `${indent}    value: "${arg.slice(eq + 1)}"`);
  }
  if (extra.length) {
    text = text.replace(/^(\s*)env:\s*$/m, (line) => `${line}\n${extra.join("\n")}`);
  }
  process.stdout.write(text.endsWith("\n") ? text : `${text}\n`);
}

function commandConfigmapFromFile(name, namespace, key, file) {
  commandConfigmapFromFiles(name, namespace, [`${key}=${file}`]);
}

// ConfigMap from several files: KEY=FILE arguments (an empty FILE gives "").
function commandConfigmapFromFiles(name, namespace, pairs) {
  const data = {};
  for (const pair of pairs) {
    const eq = pair.indexOf("=");
    if (eq <= 0) {
      console.error(`ERROR: expected KEY=FILE, got '${pair}'`);
      process.exit(1);
    }
    const file = pair.slice(eq + 1);
    data[pair.slice(0, eq)] = file ? fs.readFileSync(file, "utf8") : "";
  }
  process.stdout.write(
    JSON.stringify({ apiVersion: "v1", kind: "ConfigMap", metadata: { name, namespace }, data }) + "\n"
  );
}

const [command, ...args] = process.argv.slice(2);

switch (command) {
  case "print-configmaps":
    if (args.length !== 1) usage();
    commandPrintConfigmaps(args[0]);
    break;
  case "clone-job":
    if (args.length !== 4) usage();
    commandCloneJob(args[0], args[1], args[2], args[3]);
    break;
  case "urlencode":
    if (args.length !== 1) usage();
    commandUrlencode(args[0]);
    break;
  case "filter-events":
    if (args.length !== 5) usage();
    commandFilterEvents(args[0], args[1], args[2], args[3], args[4]);
    break;
  case "clone-job-env":
    if (args.length < 3) usage();
    commandCloneJobEnv(args[0], args[1], args[2], args.slice(3));
    break;
  case "pod-snapshot":
    commandPodSnapshot();
    break;
  case "hpa-snapshot":
    commandHpaSnapshot();
    break;
  case "shuffle-plan":
    if (args.length !== 2) usage();
    commandShufflePlan(args[0], args[1]);
    break;
  case "render-deployment":
    if (args.length < 2) usage();
    commandRenderDeployment(args[0], args[1], args.slice(2));
    break;
  case "configmap-from-file":
    if (args.length !== 4) usage();
    commandConfigmapFromFile(args[0], args[1], args[2], args[3]);
    break;
  case "configmap-from-files":
    if (args.length < 3) usage();
    commandConfigmapFromFiles(args[0], args[1], args.slice(2));
    break;
  default:
    usage();
}
