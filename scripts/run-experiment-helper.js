#!/usr/bin/env node

const fs = require("fs");

function usage() {
  console.error(
    "Usage: run-experiment-helper.js <print-configmaps|clone-job|urlencode|filter-events> ..."
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
      BASE_RPS: process.env.AUTH_BASE_RPS,
      PEAK_RPS: process.env.AUTH_PEAK_RPS,
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
  default:
    usage();
}
