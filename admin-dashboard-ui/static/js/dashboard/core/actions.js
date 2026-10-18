/**
 * Named actions triggered by [data-action] elements and menu items.
 * Core registers viewing actions; builder/index.js registers editing actions for admins.
 */
const registry = new Map();

export function registerActions(map) {
    for (const [name, fn] of Object.entries(map)) registry.set(name, fn);
}

export function runAction(name, detail) {
    const fn = registry.get(name);
    if (fn) fn(detail);
    return !!fn;
}
