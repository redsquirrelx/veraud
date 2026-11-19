import java.sql.*;

public class UserDao {
    public ResultSet find(Connection conn, String name) throws SQLException {
        PreparedStatement ps = conn.prepareStatement("SELECT * FROM users WHERE name = ?");
        ps.setString(1, name);
        return ps.executeQuery();
    }
}
