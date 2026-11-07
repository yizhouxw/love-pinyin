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
            } else if version != 1 {
                throw ClassroomError("IOS_STORAGE_VERSION_UNSUPPORTED")
            }
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

    func save(_ state: Data) throws {
        // This statement is one implicit SQLite transaction. The caller publishes
        // the new in-memory state only after SQLite has committed it.
        try statement("""
            INSERT INTO classroom (id, state) VALUES (1, ?)
            ON CONFLICT(id) DO UPDATE SET state=excluded.state
            """) { stmt in
            let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
            guard state.count <= Int(Int32.max),
                  state.withUnsafeBytes({ bytes in
                      sqlite3_bind_blob(stmt, 1, bytes.baseAddress, Int32(bytes.count), transient)
                  }) == SQLITE_OK, sqlite3_step(stmt) == SQLITE_DONE
            else { throw ClassroomError("IOS_STORAGE_UNAVAILABLE") }
        }
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
