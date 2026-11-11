import Foundation
import SQLite3

struct ClassroomError: Error {
    let code: String

    init(_ code: String) { self.code = code }
}

final class ClassroomStore {
    private var db: OpaquePointer?

    init(url: URL) throws {
        var connection: OpaquePointer?
        let status = sqlite3_open_v2(url.path, &connection, SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE, nil)
        guard status == SQLITE_OK, let connection else {
            if let connection { sqlite3_close(connection) }
            throw ClassroomError("IOS_STORAGE_UNAVAILABLE")
        }
        db = connection
        do {
            let version = try statement("PRAGMA user_version") { stmt -> Int32 in
                guard sqlite3_step(stmt) == SQLITE_ROW else { throw ClassroomError("IOS_STORAGE_UNAVAILABLE") }
                return sqlite3_column_int(stmt, 0)
            }
            if version == 0 {
                try execute("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE classroom (id INTEGER PRIMARY KEY CHECK (id=1), state BLOB NOT NULL);
                    PRAGMA user_version=1;
                    COMMIT;
                    """)
            } else if version != 1 && version != 2 {
                throw ClassroomError("IOS_STORAGE_VERSION_UNSUPPORTED")
            }
            try execute("""
                CREATE TABLE IF NOT EXISTS classroom_history (
                    kind TEXT NOT NULL, key TEXT NOT NULL, payload BLOB NOT NULL, UNIQUE(kind, key)
                );
                """)
        } catch {
            sqlite3_close(connection)
            db = nil
            throw error
        }
    }

    deinit { if let db { sqlite3_close(db) } }

    func load() throws -> Data? {
        try statement("SELECT state FROM classroom WHERE id=1") { stmt in
            switch sqlite3_step(stmt) {
            case SQLITE_DONE: return nil
            case SQLITE_ROW:
                guard let bytes = sqlite3_column_blob(stmt, 0) else {
                    throw ClassroomError("IOS_STORAGE_INVALID")
                }
                return Data(bytes: bytes, count: Int(sqlite3_column_bytes(stmt, 0)))
            default: throw ClassroomError("IOS_STORAGE_UNAVAILABLE")
            }
        }
    }

    typealias History = (kind: String, key: String, payload: Data)

    func history(_ visit: (History) throws -> Void) throws {
        try statement("SELECT kind, key, payload FROM classroom_history ORDER BY rowid") { stmt in
            while true {
                switch sqlite3_step(stmt) {
                case SQLITE_DONE: return
                case SQLITE_ROW:
                    guard let kind = sqlite3_column_text(stmt, 0),
                          let key = sqlite3_column_text(stmt, 1),
                          let bytes = sqlite3_column_blob(stmt, 2)
                    else { throw ClassroomError("IOS_STORAGE_INVALID") }
                    try visit((String(cString: kind), String(cString: key),
                               Data(bytes: bytes, count: Int(sqlite3_column_bytes(stmt, 2)))))
                default: throw ClassroomError("IOS_STORAGE_UNAVAILABLE")
                }
            }
        }
    }

    func save(_ state: Data, history: [History], replacing: Bool) throws {
        try execute("BEGIN IMMEDIATE")
        do {
            if replacing { try execute("DELETE FROM classroom_history") }
            if !history.isEmpty {
                try statement("INSERT INTO classroom_history (kind, key, payload) VALUES (?, ?, ?)") { stmt in
                    for row in history {
                        let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
                        guard sqlite3_bind_text(stmt, 1, row.kind, -1, transient) == SQLITE_OK,
                              sqlite3_bind_text(stmt, 2, row.key, -1, transient) == SQLITE_OK
                        else { throw ClassroomError("IOS_STORAGE_UNAVAILABLE") }
                        try write(row.payload, to: stmt, index: 3)
                        sqlite3_reset(stmt)
                    }
                }
            }
            try statement("""
                INSERT INTO classroom (id, state) VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET state=excluded.state
                """) { stmt in
                try write(state, to: stmt, index: 1)
            }
            try execute("PRAGMA user_version=2; COMMIT;")
        } catch {
            try? execute("ROLLBACK")
            throw error
        }
    }

    private func write(_ data: Data, to stmt: OpaquePointer, index: Int32) throws {
        let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
        guard data.count <= Int(Int32.max),
              data.withUnsafeBytes({ bytes in
                  sqlite3_bind_blob(stmt, index, bytes.baseAddress, Int32(bytes.count), transient)
              }) == SQLITE_OK, sqlite3_step(stmt) == SQLITE_DONE
        else { throw ClassroomError("IOS_STORAGE_UNAVAILABLE") }
    }

    private func statement<T>(_ sql: String, _ run: (OpaquePointer) throws -> T) throws -> T {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw ClassroomError("IOS_STORAGE_UNAVAILABLE")
        }
        defer { sqlite3_finalize(stmt) }
        return try run(stmt)
    }

    private func execute(_ sql: String) throws {
        guard sqlite3_exec(db, sql, nil, nil, nil) == SQLITE_OK else {
            throw ClassroomError("IOS_STORAGE_UNAVAILABLE")
        }
    }
}
