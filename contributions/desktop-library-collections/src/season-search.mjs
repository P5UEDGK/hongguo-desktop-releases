const jl = "零一二三四五六七八九", HR = e => e.normalize("NFKC").replace(/[\p{P}\p{Z}\s]/gu, "").toLowerCase();

function zR(e) {
    if (/^\d+$/.test(e)) return Number(e);
    if ("两" === e) return 2;
    if (e.includes("十")) {
        const [t, r] = e.split("十");
        return 10 * (t ? jl.indexOf(t) : 1) + (r ? jl.indexOf(r) : 0);
    }
    return jl.indexOf(e);
}

function VR(e) {
    return e < 10 ? jl[e] : `${e >= 20 ? jl[Math.floor(e / 10)] : ""}十${e % 10 ? jl[e % 10] : ""}`;
}

// Original display/storage text stays untouched. Only comparison keys normalize.
function Ts(title) {
    if (typeof title !== "string") return null;
    const text = title.trim();
    const explicit = text.match(/^(.*?)第?([一二两三四五六七八九十\d０-９]{1,3})季[\s！!。]*$/u);
    const numbered = explicit ? null : text.match(/^(.*?[^\d０-９])([\d０-９]{1,2})$/u);
    const base = (explicit?.[1] || numbered?.[1] || text).trim();
    const season = explicit ? zR(explicit[2].normalize("NFKC")) : numbered ? Number(numbered[2].normalize("NFKC")) : 1;
    return !base || base.length > 65 || season < 1 || season >= 99 || /第.+季|完结篇|合集|完整版|[上下]部/.test(base) ? null : {
        base: base,
        key: HR(base),
        season: season,
        explicit: !!explicit
    };
}

function seasonSearchQueries(title) {
    const parsed = Ts(title);
    if (!parsed) return [];
    const prefix = parsed.base.split(/[？?！!：:]/u, 1)[0].trim();
    return [ ...new Set([ parsed.base, ...prefix.length >= 2 && prefix !== parsed.base ? [ prefix ] : [] ]) ];
}

function desktopSeasonTitleCandidate(seed, candidate) {
    const original = Ts(seed), other = Ts(candidate);
    if (!original || !other) return false;
    if (original.key === other.key) return true;
    const head = value => value.base.split(/[？?！!：:]/u, 1)[0].trim();
    const a = head(original), b = head(other);
    return a.length >= 2 && b.length >= 2 && HR(a) === HR(b);
}

async function KR(api, seed, live = () => true, options = {}) {
    const parsed = Ts(seed.title);
    if (!parsed) return {
        items: [],
        automatic: false,
        incomplete: false
    };
    const kind = Bd(seed), modes = kind === "short" ? [ "short", "manju" ] : [ "manju", "short" ];
    const deadline = options.deadline ?? Date.now() + 3e4;
    const accepted = new Map, queries = new Set;
    let incomplete = false;
    const result = () => {
        const rows = [ ...accepted.values() ].sort((a, b) => Ts(a.title).season - Ts(b.title).season || a.seriesId.localeCompare(b.seriesId));
        return {
            items: rows,
            automatic: false,
            incomplete
        };
    };
    async function bounded(work) {
        let timer;
        try {
            return await Promise.race([ Promise.resolve().then(work), new Promise((resolve, reject) => {
                timer = setTimeout(() => reject(Error("timeout")), Math.max(1, deadline - Date.now()));
            }) ]);
        } finally {
            clearTimeout(timer);
        }
    }
    for (const query of seasonSearchQueries(seed.title)) {
        const candidates = new Map;
        const preserveCandidates = () => {
            for (const [id, row] of candidates) accepted.set(id, row);
        };
        let failed = false, truncated = false;
        for (const mode of modes) {
            const pages = new Set;
            for (let page = 1; page <= 3; page++) {
                if (!live()) return {
                    items: [],
                    automatic: false,
                    incomplete: true
                };
                if (Date.now() >= deadline) {
                    incomplete = true;
                    preserveCandidates();
                    return result();
                }
                const identity = JSON.stringify([ query, page, mode ]);
                if (queries.has(identity)) continue;
                queries.add(identity);
                try {
                    const response = await bounded(() => api.searchNovelfm(query, page, mode));
                    if (!live()) return {
                        items: [],
                        automatic: false,
                        incomplete: true
                    };
                    if (response.page !== page || response.mode !== mode || response.source !== "novelfm" || !Array.isArray(response.items) || response.items.length > 20) throw Error("invalid page");
                    const signature = JSON.stringify(response.items.map(row => row.seriesId));
                    if (pages.has(signature)) {
                        truncated = true;
                        break;
                    }
                    pages.add(signature);
                    for (const row of response.items) {
                        if (typeof row.title !== "string" || !Array.isArray(row.tags) || !Array.isArray(row.actors)) continue;
                        const season = Ts(row.title), candidateKind = Bd(row);
                        if (typeof row.seriesId === "string" && /^\d{8,24}$/.test(row.seriesId) && row.seriesId !== seed.seriesId && season && desktopSeasonTitleCandidate(seed.title, row.title) && (!kind || !candidateKind || kind === candidateKind) && (options.targetSeason === undefined || season.season === options.targetSeason)) candidates.set(row.seriesId, row);
                    }
                    if (!response.hasMore) break;
                    if (page === 3) truncated = true;
                } catch {
                    incomplete = true;
                    failed = true;
                    break;
                }
            }
            if (failed) break;
        }
        incomplete ||= truncated;
        if (!live()) return {
            items: [],
            automatic: false,
            incomplete: true
        };
        let resolved;
        if (Date.now() >= deadline) {
            incomplete = true;
            preserveCandidates();
            return result();
        }
        try {
            resolved = api.resolveSeasonCandidates ? await bounded(() => api.resolveSeasonCandidates(seed, [ ...candidates.values() ], live)) : {
                items: [ ...candidates.values() ],
                verified: false
            };
        } catch {
            incomplete = true;
            // Keep already fetched rows for the collection owner's final
            // relationship check. Unverified rows never become auto-favorites.
            preserveCandidates();
            return result();
        }
        if (!live()) return {
            items: [],
            automatic: false,
            incomplete: true
        };
        for (const row of resolved.items) if (candidates.has(row.seriesId)) accepted.set(row.seriesId, row);
        // An error or truncated page is not proof that the original query has no match.
        if (resolved.verified || failed || truncated || Date.now() >= deadline) break;
    }
    return result();
}

function Bd(e) {
    return e.tags.some(e => /AI剧|AI短剧/i.test(e)) ? "ai" : e.tags.some(e => [ "漫剧", "动漫", "动画", "205" ].includes(e)) ? "manju" : e.tags.some(e => [ "真人", "真人剧" ].includes(e)) ? "short" : null;
}

async function qR(e, t, r = () => !0) {
    const seed = t, n = Ts(t.title);
    if (!n) return {
        items: [],
        automatic: !1,
        incomplete: !1
    };
    const i = n.season + 1, s = Bd(t), a = "short" === s ? [ "short", "manju" ] : [ "manju", "short" ], o = [ ...new Set([ `${n.base}第${VR(i)}季`, `${n.base}第${i}季` ]) ], l = new Map, c = new Map;
    let d = !1, u = !1;
    const h = Date.now() + 3e4;
    async function f(e) {
        let t;
        try {
            return await Promise.race([ e, new Promise((e, r) => {
                t = setTimeout(() => r(new Error("timeout")), Math.max(1, h - Date.now()));
            }) ]);
        } finally {
            clearTimeout(t);
        }
    }
    async function p(s, m, g = 1) {
        if (!r() || Date.now() >= h) d = !0; else try {
            const d = await f(e.searchNovelfm(s, g, m));
            if (!r()) return;
            if (d.page !== g || d.mode !== m || "novelfm" !== d.source || !Array.isArray(d.items) || d.items.length > 20) throw new Error("invalid page");
            d.hasMore && (u = !0), 1 === g && m === a[0] && o.includes(s) && d.items[0] && c.set(s, d.items[0].seriesId);
            for (const e of d.items) {
                const r = Ts(e.title);
                /^\d{8,24}$/.test(e.seriesId) && e.seriesId !== t.seriesId && r?.key === n.key && r.season === i && l.set(e.seriesId, e);
            }
            d.hasMore && 1 === g && m === a[0] && o.includes(s) && await p(s, m, 2);
        } catch {
            d = !0;
        }
    }
    for (const e of o) for (const t of a) await p(e, t);
    let related = false;
    try { if (e.resolveSeasonCandidates) {
        const s = await f(e.resolveSeasonCandidates(t, [ ...l.values() ], r));
        l.clear();
        for (const e of s.items) l.set(e.seriesId, e);
        related = s.verified;
    } } catch { return {items:[],automatic:false,incomplete:true}; }
    if (!related && !d && !u && r()) {
        const s = await KR(e, t, r, {
            deadline: h,
            targetSeason: i
        });
        d ||= s.incomplete;
        for (const e of s.items) l.set(e.seriesId, e);
    }
    const m = [];
    l.size > 5 && (d = !0);
    for (const t of [ ...l.values() ].slice(0, 5)) {
        if (!r() || Date.now() >= h) {
            d = !0;
            break;
        }
        try {
            const s = await f(e.validationEpisodes(t.seriesId));
            if (!r()) break;
            const a = s.title ? Ts(s.title) : null, verified = e.resolveSeasonCandidates ? await f(e.resolveSeasonCandidates(seed, [ t ], r)) : null;
            if (s.seriesId !== t.seriesId || !Number.isSafeInteger(s.total) || s.total < 1 || s.total > 1e5 || !Array.isArray(s.episodes) || !s.episodes.includes(1) || s.title && (!verified?.verified && a?.key !== n.key || a?.season !== i)) {
                d = !0;
                continue;
            }
            m.push({
                ...t,
                episodeCount: s.total
            });
        } catch {
            d = !0;
        }
    }
    const g = m[0], b = g && (!t.actors.length || !g.actors.length || t.actors.some(e => g.actors.includes(e)));
    return u && (!g || !o.every(e => c.get(e) === g.seriesId)) && (d = !0), {
        items: m,
        incomplete: d,
        automatic: r() && !d && related && 1 === l.size && 1 === m.length && n.explicit && !!Ts(g.title)?.explicit && Ts(g.title)?.key===n.key && !!s && Bd(g) === s && !!b
    };
}

export { Ts as parseSeasonTitle, KR as findOtherSeasons, qR as findNextSeason, seasonSearchQueries };
