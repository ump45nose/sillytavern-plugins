import SwiftUI

struct LoadingBanner: View {
    let message: String
    var body: some View {
        HStack(spacing: 10) {
            ProgressView().controlSize(.small)
            Text(message).font(.caption).foregroundStyle(.secondary)
            Spacer()
        }.padding(.horizontal, 24).padding(.vertical, 10)
            .background(Color.indigo.opacity(0.045))
            .accessibilityElement(children: .combine)
    }
}

struct PageLoadingView: View {
    let message: String
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            ProgressView(message).frame(maxWidth: .infinity).padding(.vertical, 30)
            ForEach(0..<3) { _ in
                VStack(alignment: .leading, spacing: 14) {
                    RoundedRectangle(cornerRadius: 4).frame(width: 150, height: 16)
                    RoundedRectangle(cornerRadius: 4).frame(height: 12)
                    RoundedRectangle(cornerRadius: 4).frame(maxWidth: 420).frame(height: 12)
                }.foregroundStyle(Color.primary.opacity(0.065)).padding(24)
                    .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 14))
                    .accessibilityHidden(true)
            }
        }
    }
}
