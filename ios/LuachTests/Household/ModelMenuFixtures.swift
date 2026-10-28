import Foundation
@testable import Luach

/// The owner's model menu (`/api/models/manage`, `/api/models/catalogue`) in the shapes the
/// server's routes give (src/luach/routes/models.py), with made-up models and hosts.
enum ModelMenuFixtures {
    static func model(
        _ id: String, name: String, local: Bool = false, provider: String = "", providerSet: String = "",
        enabled: Bool = true, position: Int, isDefault: Bool = false, health: [String: Any] = ok,
        trial: Any = NSNull(), meta: [String: Any] = [:], lastOk: Any = "2026-10-28T09:00:00+00:00",
        about: String = ""
    ) -> [String: Any] {
        [
            "id": id, "name": name, "about": about, "local": local, "provider": provider,
            "provider_set": providerSet, "enabled": enabled, "position": position, "meta": meta,
            "failures": 0, "last_ok_at": lastOk, "health": health, "is_default": isDefault, "trial": trial,
        ]
    }

    static let ok: [String: Any] = ["status": "ok", "since": NSNull(), "reason": ""]
    static let down: [String: Any] = [
        "status": "not_answering", "since": "2026-10-28T08:00:00+00:00", "reason": "its provider refused it — 404 no such model",
    ]

    static func score(_ passed: Int, _ total: Int, _ verdict: String) -> [String: Any] {
        ["passed": passed, "total": total, "verdict": verdict, "at": "2026-10-27T20:00:00+00:00"]
    }

    static func trial(
        id: Int = 7, model: String = "deepseek/deepseek-v4-flash", status: String = "running", done: Int = 3,
        passed: Int = 3, total: Int = 12, verdict: Any = NSNull(), cases: [[String: Any]] = [], error: String = ""
    ) -> [String: Any] {
        [
            "id": id, "model": model, "status": status, "requested_by": "robin",
            "started_at": "2026-10-28T10:00:00+00:00",
            "finished_at": status == "running" ? NSNull() : "2026-10-28T10:03:00+00:00",
            "done": done, "passed": passed, "total": total, "verdict": verdict, "cases": cases, "error": error,
        ]
    }

    static let cases: [[String: Any]] = [
        ["case": "add_event", "about": "Adds an event on a day", "ok": true, "problems": [], "tools": [["add_event"]]],
        ["case": "list_tasks", "about": "", "ok": false, "problems": ["called no tool"], "tools": []],
    ]

    static let home = model("qwen3.6-35b", name: "Home server · Qwen 3.6", local: true, position: 0, isDefault: true,
                            trial: score(12, 12, "good"), meta: ["context_length": 131072, "tools": true],
                            about: "Runs on the household's own machine.")
    static let flash = model("deepseek/deepseek-v4-flash", name: "DeepSeek V4 Flash", provider: "DeepSeek",
                             position: 1, trial: score(10, 12, "fair"),
                             meta: ["context_length": 1_048_576, "tools": true, "price_in": 0.3, "price_out": 1.2])
    static let gemini = model("openrouter/google/gemini-3.8-flash", name: "Gemini 3.8 Flash",
                              provider: "Google, through OpenRouter", enabled: false, position: 2, health: down,
                              trial: score(6, 12, "low"), lastOk: NSNull())

    static func snapshot(
        models: [[String: Any]] = [home, flash, gemini], trial: Any = NSNull(), left: Int = 5,
        configured: Bool = true, default id: String = "qwen3.6-35b", catalogue: Bool = true
    ) -> [String: Any] {
        [
            "default": id, "configured": configured, "models": models, "trial": trial,
            "trials_left_today": left,
            "catalogue": ["configured": catalogue, "source": catalogue ? "models.example.com" : ""],
        ]
    }

    static func entry(
        _ id: String, name: String, context: Any = 131072, tools: Any = true, priceIn: Any = 0.2,
        priceOut: Any = 0.8, alias: Bool = false, onMenu: Bool = false, aliasOfIt: String = ""
    ) -> [String: Any] {
        [
            "id": id, "name": name, "context_length": context, "tools": tools, "price_in": priceIn,
            "price_out": priceOut, "alias": alias, "provider": "DeepSeek, through OpenRouter",
            "on_menu": onMenu, "recommended": alias, "alias_of_it": aliasOfIt,
        ]
    }

    static let catalogue: [String: Any] = [
        "configured": true, "source": "models.example.com", "error": "",
        "models": [
            entry("~deepseek/deepseek-flash-latest", name: "DeepSeek Flash (latest)", alias: true),
            entry("deepseek/deepseek-v4-flash", name: "DeepSeek V4 Flash", onMenu: true),
            entry("deepseek/deepseek-v3.2", name: "DeepSeek V3.2", context: NSNull(), tools: false, priceIn: 0,
                  priceOut: 0, aliasOfIt: "~deepseek/deepseek-flash-latest"),
            entry("acme/tiny", name: "Tiny", context: 900, tools: NSNull(), priceIn: NSNull(), priceOut: NSNull()),
        ],
    ]

    static func data(_ json: Any) -> Data {
        try! JSONSerialization.data(withJSONObject: json)
    }

    static func decode<T: Decodable>(_ type: T.Type, _ json: Any) throws -> T {
        try JSONDecoder.snake.decode(type, from: data(json))
    }
}
